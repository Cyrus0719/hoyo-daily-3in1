# -*- coding: utf-8 -*-
"""OCR 小工具：给登录兜底用。

必须用 OneDragon 的 Python 运行（那里面才有 numpy/cv2/onnxruntime/onnxocr 和 ppocrv6 模型）：
    D:\\daily\\OneDragon-ref\\.venv\\Scripts\\python.exe ocr_helper.py

两种用法：
  1) 常驻模式（推荐，模型只加载一次）：从 stdin 逐行读 JSON {"img": "路径"}，往 stdout 写一行 JSON {"ok": true, "boxes": [...]}
  2) 单次：python ocr_helper.py --img 路径   直接打印同样的一行 JSON
每个 box: {"text","score","x1","y1","x2","y2"}（坐标相对图片左上角，像素）
"""
import sys
import os
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "OneDragon-ref", "src")
MODELS = os.path.join(HERE, "OneDragon-ref", "assets", "models", "onnx_ocr", "ppocrv6")
sys.path.insert(0, SRC)

_engine = None


def _get_engine():
    global _engine
    if _engine is not None:
        return _engine
    import numpy as np  # noqa: F401
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
    kw = dict(
        det_model_dir=os.path.join(MODELS, "det.onnx"),
        rec_model_dir=os.path.join(MODELS, "rec.onnx"),
        cls_model_dir=os.path.join(MODELS, "cls.onnx"),
        rec_char_dict_path=os.path.join(MODELS, "ppocrv6_dict.txt"),
        vis_font_path=os.path.join(MODELS, "simfang.ttf"),
        use_angle_cls=False,
        ocr_model_name="ppocrv6",
    )
    kw = {k: v for k, v in kw.items() if os.path.exists(v) or k in ("use_angle_cls", "ocr_model_name")}
    _engine = ONNXPaddleOcr(**kw)
    return _engine


def ocr_file(path):
    import cv2
    import numpy as np
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return {"ok": False, "error": "decode failed"}
    res = _get_engine().ocr(img)
    boxes = []
    items = []
    for page in (res or []):
        if isinstance(page, (list, tuple)):
            for it in page:
                items.append(it)
        else:
            items.append(page)
    for item in items:
        try:
            box, rec = item[0], item[1]
            text, score = rec[0], float(rec[1])
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            boxes.append({
                "text": str(text),
                "score": round(score, 4),
                "x1": int(min(xs)), "y1": int(min(ys)),
                "x2": int(max(xs)), "y2": int(max(ys)),
            })
        except Exception:
            continue
    return {"ok": True, "boxes": boxes}


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default="")
    args = ap.parse_args()
    if args.img:
        print(json.dumps(ocr_file(args.img)))
        return
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            out = ocr_file(req["img"])
        except Exception as e:  # noqa: BLE001
            out = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        out["img"] = ""
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    _main()
