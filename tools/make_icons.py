"""生成 Tauri 应用图标（纯标准库，无需 Pillow）。
雷达风格：深空底 + 青色同心圆 + 扫描线 + 中心点。
输出：frontend/src-tauri/icons/{32x32,128x128,128x128@2x,icon}.png + icon.ico
"""
import math
import os
import struct
import zlib

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "src-tauri", "icons")


def png_bytes(size: int, rgba: bytes) -> bytes:
    rows = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def render(size: int) -> bytes:
    cx = cy = (size - 1) / 2.0
    r = size / 2.0
    out = bytearray()
    for y in range(size):
        for x in range(size):
            dx, dy = x - cx, y - cy
            d = math.hypot(dx, dy)
            R, G, B, A = 10, 16, 30, 255                     # 深空底
            if d > r * 0.99:
                A = 0                                        # 圆角外透明
            else:
                # 底部轻微渐变，增加层次
                t = y / max(1.0, size - 1.0)
                R, G, B = int(10 + 6 * t), int(16 + 10 * t), int(30 + 18 * t)
            for rr in (0.30, 0.52, 0.74, 0.94):               # 同心圆环
                if abs(d - rr * r) <= max(1.0, size * 0.016):
                    R, G, B = 34, 211, 238
            if 40 <= (math.degrees(math.atan2(dy, dx)) % 360) <= 51 and d <= 0.94 * r:  # 扫描线
                R, G, B = 125, 211, 252
            if d <= 0.11 * r:                                 # 中心点
                R, G, B = 34, 211, 238
            out += bytes((R, G, B, A))
    return bytes(out)


def ico_bytes(png256: bytes) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png256), 22)
    return header + entry + png256


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    targets = {"32x32.png": 32, "128x128.png": 128, "128x128@2x.png": 256, "icon.png": 512}
    for name, size in targets.items():
        with open(os.path.join(OUT_DIR, name), "wb") as f:
            f.write(png_bytes(size, render(size)))
        print("wrote", name, size)
    with open(os.path.join(OUT_DIR, "icon.ico"), "wb") as f:
        f.write(ico_bytes(png_bytes(256, render(256))))
    print("wrote icon.ico")


if __name__ == "__main__":
    main()
