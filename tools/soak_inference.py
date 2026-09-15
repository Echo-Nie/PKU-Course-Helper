"""Repeated local ONNX inference, including image decoding; no school requests."""
import argparse
import gc
import io
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
from soak_desktop import resources
from autoelective.inference import OnnxPredictor
from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--iterations', type=int, default=2000)
    args = parser.parse_args()
    if Path(__file__).resolve().parents[2] not in args.report.resolve().parents:
        raise ValueError('Report must stay in testing workspace')
    output = io.BytesIO()
    with Image.new('RGB', (130, 52), (230, 240, 250)) as source: source.save(output, format='GIF')
    image = output.getvalue()
    model = OnnxPredictor(); model.startSession(); session = model._session
    samples = []; started = time.monotonic()
    try:
        for i in range(1, args.iterations + 1):
            model.predictOneCaptcha(image)
            assert model._session is session
            if i in (100, 500, 1000, args.iterations):
                gc.collect()
                samples.append({'inferences': i, **resources()})
                print(json.dumps(samples[-1]), flush=True)
    finally:
        model.closeSession()
    growth = samples[-1]['private_bytes'] - samples[0]['private_bytes']
    handles = samples[-1]['handles'] - samples[0]['handles']
    report = {'passed': growth < 8_000_000 and handles <= 4, 'inferences': args.iterations,
              'native_thread_limit': 1,
              'seconds': round(time.monotonic() - started, 3), 'single_session_reused': True,
              'private_growth_after_warmup': growth, 'handle_growth_after_warmup': handles,
              'samples': samples, 'real_school_captcha_accuracy_tested': False}
    args.report.write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
