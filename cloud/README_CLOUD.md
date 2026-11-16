# Training the Amharic base model on a rented GPU (RunPod)

Trains facebook/w2v-bert-2.0 (MIT licence) on WAXAL + FLEURS Amharic. Voice-neutral: no personal recordings.
Result: MY_AMHARIC_MODEL.zip — a model for the app. Keep final/README.md (data attribution).
Before selling: check the licence of the WAXAL Amharic subset (the dataset page lists CC BY 4.0 and CC BY-SA 4.0).

1. runpod.io → sign up → Billing → add about $25.
2. huggingface.co → sign up (free) → Settings → Access Tokens → Create new token → type "Read" → copy it.
   Open huggingface.co/datasets/google/WaxalNLP; if it asks you to accept terms, accept.
3. RunPod → Pods → Deploy:
   GPU: RTX 4090 (24 GB). Secure Cloud = reliable; Community Cloud = cheaper but the machine can go offline.
   Template: "Runpod PyTorch 2.x". Edit template: Container disk 50 GB, Volume disk 200 GB (mounted at /workspace).
   Pricing: On-Demand → Deploy.
4. When the pod shows Running: Connect → Jupyter Lab. Drag AmharicDictate-cloud-upload.zip into the left file panel.
5. In Jupyter: File → New → Terminal, then type:
       cd /workspace && unzip -o AmharicDictate-cloud-upload.zip -d amharic && cd amharic
       pip install -q -U "huggingface_hub[cli]" && hf auth login    (paste the token; answer n to "git credential")
       bash run_on_gpu.sh test               (10-15 min; must end with "TEST OK")
       nohup bash run_on_gpu.sh full > log.txt 2>&1 &
       tail -f log.txt                       (watch; Ctrl+C stops watching, not training)
   You can close the browser; training keeps running. Check later: Connect → Jupyter → terminal → tail -f amharic/log.txt
   If the pod restarted: run the nohup line again — it resumes from the last checkpoint.
6. Done when log.txt ends with "== DONE". Right-click amharic/MY_AMHARIC_MODEL.zip → Download.
   Then in RunPod: Stop the pod, then Terminate/Delete it (a stopped pod with a volume still costs a little).
7. Send the zip to your PC; I'll install it in the app.
