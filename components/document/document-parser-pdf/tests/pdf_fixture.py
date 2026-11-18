"""手工构造最小合法 PDF 的测试夹具（避免引入 reportlab 等生成库）。"""

from __future__ import annotations

def build_pdf(pages, images_per_page=0, title=None):
    """pages: list[list[str]] 每页的文本行。images_per_page: 每页内嵌 1x1 图片数。"""
    objs: list[bytes] = [b"", b""]  # 预留 1=Catalog 2=Pages
    def add(body: bytes) -> int:
        objs.append(body); return len(objs)
    page_ids, content_ids, font_id, image_ids = [], [], None, []
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for _ in range(images_per_page):
        image_ids.append(add(b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
                             b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 3 >>\nstream\n"
                             + b"\xff\xff\xff" + b"\nendstream"))
    for lines in pages:
        ops = ["BT /F1 12 Tf 72 720 Td"]
        for i, line in enumerate(lines):
            esc = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            ops.append(f"0 -{14*i} Td ({esc}) Tj" if i else f"({esc}) Tj")
        ops.append("ET")
        for k in range(images_per_page):
            ops.append(f"/Im{k} Do")
        stream = "\n".join(ops).encode("latin-1", "replace")
        cid = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        content_ids.append(cid)
        xobj = b""
        if image_ids:
            entries = b" ".join(f"/Im{k} {image_ids[k]} 0 R".encode() for k in range(images_per_page))
            xobj = b" /XObject << " + entries + b" >>"
        pid = add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents "
                  + str(cid).encode() + b" 0 R /Resources << /Font << /F1 "
                  + str(font_id).encode() + b" 0 R >>" + xobj + b" >> >>")
        page_ids.append(pid)
    kids = b" ".join(f"{p} 0 R".encode() for p in page_ids)
    objs[1] = b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(page_ids)).encode() + b" >>"
    info_id = None
    if title:
        t = title.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        info_id = add(b"<< /Title (" + t.encode("latin-1","replace") + b") >>")
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    trailer = b"<< /Size " + str(len(objs)+1).encode() + b" /Root 1 0 R"
    if info_id: trailer += b" /Info " + str(info_id).encode() + b" 0 R"
    out += b"trailer\n" + trailer + b" >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n"
    return bytes(out)

