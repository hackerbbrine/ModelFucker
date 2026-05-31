"""
gguf_parser.py — Minimal GGUF header parser.
Reads only the metadata + tensor index, never the weight data.
Used to find attention tensor byte ranges for targeted/protected corruption.
"""

import struct
import os
from dataclasses import dataclass, field

GGUF_MAGIC      = 0x46554747   # "GGUF"
DEFAULT_ALIGN   = 32

# KV value type IDs
_U8, _I8, _U16, _I16 = 0, 1, 2, 3
_U32, _I32, _F32, _BOOL = 4, 5, 6, 7
_STR, _ARRAY, _U64, _I64, _F64 = 8, 9, 10, 11, 12

# Attention tensor name fragments — anything matching one of these is an attention tensor
ATTN_KEYWORDS = {
    "attn", "attention", "q_proj", "k_proj", "v_proj", "o_proj",
    "query", "key", "value", "self_attn", "q_", "k_", "v_",
}


@dataclass
class TensorInfo:
    name: str
    dims: list
    dtype: int
    offset: int       # relative to data section start
    abs_start: int = 0
    abs_end: int   = 0

    @property
    def is_attention(self) -> bool:
        n = self.name.lower()
        return any(kw in n for kw in ATTN_KEYWORDS)


@dataclass
class GGUFInfo:
    version: int
    metadata: dict
    tensors: list
    data_offset: int              # absolute file offset where tensor data begins
    attention_head_count: int = 0
    attention_kv_count: int   = 0

    @property
    def attention_tensors(self):
        return [t for t in self.tensors if t.is_attention]

    @property
    def attention_ranges(self) -> list:
        """Absolute (start, end) byte ranges of all attention tensors."""
        return [(t.abs_start, t.abs_end) for t in self.attention_tensors if t.abs_end > t.abs_start]

    def summary(self) -> str:
        at = self.attention_tensors
        total_bytes = sum(t.abs_end - t.abs_start for t in at if t.abs_end > t.abs_start)
        return (
            f"{len(at)} attention tensors  "
            f"({total_bytes / 1024 / 1024:.0f} MB)  "
            f"heads={self.attention_head_count}"
        )


class _Reader:
    def __init__(self, f):
        self._f = f

    def u8(self):  return struct.unpack('<B', self._f.read(1))[0]
    def i8(self):  return struct.unpack('<b', self._f.read(1))[0]
    def u16(self): return struct.unpack('<H', self._f.read(2))[0]
    def i16(self): return struct.unpack('<h', self._f.read(2))[0]
    def u32(self): return struct.unpack('<I', self._f.read(4))[0]
    def i32(self): return struct.unpack('<i', self._f.read(4))[0]
    def f32(self): return struct.unpack('<f', self._f.read(4))[0]
    def u64(self): return struct.unpack('<Q', self._f.read(8))[0]
    def i64(self): return struct.unpack('<q', self._f.read(8))[0]
    def f64(self): return struct.unpack('<d', self._f.read(8))[0]
    def boolean(self): return bool(self.u8())
    def tell(self): return self._f.tell()

    def string(self) -> str:
        length = self.u64()
        return self._f.read(length).decode('utf-8', errors='replace')

    def value(self, vtype: int):
        dispatch = {
            _U8: self.u8, _I8: self.i8, _U16: self.u16, _I16: self.i16,
            _U32: self.u32, _I32: self.i32, _F32: self.f32, _BOOL: self.boolean,
            _STR: self.string, _U64: self.u64, _I64: self.i64, _F64: self.f64,
        }
        if vtype == _ARRAY:
            elem_type = self.u32()
            count = self.u64()
            fn = dispatch.get(elem_type)
            if fn:
                return [fn() for _ in range(count)]
            return []
        fn = dispatch.get(vtype)
        if fn:
            return fn()
        raise ValueError(f"Unknown GGUF value type: {vtype}")


def parse(path: str) -> GGUFInfo:
    """
    Parse a GGUF file's header and return attention tensor metadata.
    Never reads the actual weight data — only the index.
    Raises ValueError if the file isn't a valid GGUF.
    """
    file_size = os.path.getsize(path)

    with open(path, 'rb') as f:
        r = _Reader(f)

        magic = r.u32()
        if magic != GGUF_MAGIC:
            raise ValueError(f"Not a GGUF file (magic={hex(magic)})")

        version = r.u32()

        if version == 1:
            n_tensors = r.u32()
            n_kv      = r.u32()
        else:
            n_tensors = r.u64()
            n_kv      = r.u64()

        # ── Metadata KV pairs ──────────────────────────────────────────────
        metadata = {}
        for _ in range(n_kv):
            try:
                key   = r.string()
                vtype = r.u32()
                val   = r.value(vtype)
                metadata[key] = val
            except Exception:
                break   # malformed metadata — stop here, use what we have

        # ── Tensor info ────────────────────────────────────────────────────
        tensors = []
        for _ in range(n_tensors):
            try:
                name   = r.string()
                n_dims = r.u32()
                dims   = [r.u64() for _ in range(n_dims)]
                dtype  = r.u32()
                offset = r.u64()
                tensors.append(TensorInfo(name=name, dims=dims, dtype=dtype, offset=offset))
            except Exception:
                break

        # ── Data section start (aligned) ───────────────────────────────────
        alignment = int(metadata.get('general.alignment', DEFAULT_ALIGN))
        pos = r.tell()
        if alignment > 1:
            rem = pos % alignment
            if rem:
                pos += alignment - rem
        data_offset = pos

        # ── Compute absolute byte ranges using consecutive offsets ─────────
        # Sort by offset so we can use tensor[i+1].offset - tensor[i].offset
        sorted_t = sorted(tensors, key=lambda t: t.offset)
        for i, t in enumerate(sorted_t):
            t.abs_start = data_offset + t.offset
            if i + 1 < len(sorted_t):
                t.abs_end = data_offset + sorted_t[i + 1].offset
            else:
                t.abs_end = file_size

        # Rebuild original order
        tensors = sorted(tensors, key=lambda t: t.name)

        # ── Attention head count ───────────────────────────────────────────
        head_count = 0
        for key in metadata:
            if 'head_count' in key and 'kv' not in key:
                head_count = int(metadata[key])
                break

        kv_count = 0
        for key in metadata:
            if 'head_count_kv' in key:
                kv_count = int(metadata[key])
                break

    return GGUFInfo(
        version=version,
        metadata=metadata,
        tensors=tensors,
        data_offset=data_offset,
        attention_head_count=head_count,
        attention_kv_count=kv_count,
    )


def try_parse(path: str):
    """Parse silently — returns None on any error."""
    try:
        return parse(path)
    except Exception:
        return None
