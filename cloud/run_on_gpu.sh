#!/usr/bin/env bash
# Amharic Dictate — train your own Amharic speech model (base model) on a rented GPU.
#   bash run_on_gpu.sh test    # ~10-15 minutes: checks everything works
#   bash run_on_gpu.sh full    # the real training (many hours). Safe to re-run: resumes from the last checkpoint.
# The base model is voice-neutral: personal recordings are NOT used (voice profiles add those per person).
# To include recordings anyway, put them in a voice_data folder and run with:  WITH_MY_VOICE=1 bash run_on_gpu.sh full
set -e
cd "$(dirname "$0")"
MODE="${1:-test}"

echo "== Installing libraries"
pip install -q "transformers>=4.46,<5" "datasets[audio]>=3.0" accelerate soundfile librosa "huggingface_hub[cli]"
python -c "import torch; print('GPU:', torch.cuda.get_device_name(0)); print('GPU memory: %.0f GB' % (torch.cuda.get_device_properties(0).total_memory/1e9))"

LOCAL=""
if [ "${WITH_MY_VOICE:-0}" = "1" ] && [ -d voice_data ]; then
  echo "Including your recordings: $(ls voice_data/*.wav 2>/dev/null | wc -l) clips"; LOCAL="local:voice_data@2"
fi

if [ "$MODE" = "test" ]; then
  python train_amharic_ctc.py --sources fleurs $LOCAL --max_train_samples 400 --max_steps 60 \
      --eval_steps 30 --max_eval_samples 100 --output_dir smoke_test
  echo
  echo "== TEST OK. Next:  nohup bash run_on_gpu.sh full > log.txt 2>&1 &"
else
  python train_amharic_ctc.py --sources waxal fleurs $LOCAL --epochs 3 --num_proc 16 --output_dir amharic_model
  python -c "import shutil; shutil.make_archive('MY_AMHARIC_MODEL', 'zip', 'amharic_model', 'final')"
  echo
  echo "== DONE. Download MY_AMHARIC_MODEL.zip (right-click it in the file panel), then STOP and DELETE the pod."
fi
