"""Faceless 'Life at Every Level' pipeline. LLM: Groq primary, Gemini backup."""
import argparse, json, os, random, socket, subprocess, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path
import requests

socket.setdefaulttimeout(120)
ROOT = Path(__file__).parent
EPS = ROOT / "episodes"
VOICE = "en-US-ChristopherNeural"
FPS = 30
FONT = os.environ.get("FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
IMG_URL = ("https://image.pollinations.ai/prompt/{p}"
           "?width=720&height=1280&seed={seed}&model=flux&nologo=true")
GROQ = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-20b"]

TOPICS = [
    "a poor village boy who becomes king",
    "a maid who becomes a fashion queen",
    "a street food cook who becomes a millionaire chef",
    "a fisherman who discovers an underwater kingdom",
    "a farmer's daughter who becomes a tech billionaire",
    "an orphan boy who becomes emperor",
    "a janitor who becomes a space station commander",
]

def sh(cmd):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if p.returncode != 0:
        print(f"[cmd failed] {p.stderr[-2000:]}")
        raise RuntimeError(f"command failed: {cmd[0]}")

def dur(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                                   "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.decode().strip())

DEFAULT_BIBLE = {
    "character": "a kind middle-aged farmer man, short black hair, tan skin, simple beige tunic, weathered hands",
    "style": "cinematic photorealistic, warm golden hour light, rich detail, vertical composition, game concept art quality",
    "negative": "text, watermark, logo, deformed hands, extra limbs, blurry",
    "seed": 777123,
}

WRITER_PROMPT = """You write viral TikTok "life at every level" scripts.
Topic: {topic}

CHARACTER (visual consistency — every level MUST reuse this exact character description):
{character}

STYLE (append to every visual): {style}

Return ONLY valid JSON, no markdown:
{{"title": "<clickbait <=60 chars>",
  "hook": "<opening narration line, <=15 words>",
  "levels": [
    {{"label": "Level 1",  "narration": "<punchy line <=18 words>", "visual": "<same character + STARTER environment>"}},
    {{"label": "Level 2",  "narration": "...", "visual": "..."}},
    {{"label": "Level 5",  "narration": "...", "visual": "..."}},
    {{"label": "Level 10", "narration": "...", "visual": "..."}},
    {{"label": "Level 25", "narration": "...", "visual": "..."}},
    {{"label": "Level 50", "narration": "...", "visual": "..."}},
    {{"label": "Level 100","narration": "...", "visual": "<absurd max-luxury finale>"}}
  ],
  "caption": "<caption <=150 chars>",
  "hashtags": ["#lifeateverylevel", "#villagelife", "#ai", "#fyp", "#satisfying"]}}
Rules: environment escalates mud hut -> palace/city; visuals always describe the SAME person; no real brands or real people."""

def _extract_json(txt):
    txt = txt.strip()
    i, j = txt.find("{"), txt.rfind("}")
    if i == -1 or j == -1:
        raise ValueError(f"no JSON object found in: {txt[:200]}")
    return json.loads(txt[i:j + 1])

def groq_json(prompt):
    key = os.environ["GROQ_API_KEY"]
    last = None
    for model in GROQ_MODELS:
        for attempt in range(1, 4):
            try:
                print(f"[groq] trying {model} (attempt {attempt}/3)")
                body = {"model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "response_format": {"type": "json_object"},
                        "temperature": 1.0}
                req = urllib.request.Request(
                    GROQ, data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {key}"})
                out = json.loads(urllib.request.urlopen(req, timeout=120).read())
                result = _extract_json(out["choices"][0]["message"]["content"])
                print(f"[groq] OK via {model}")
                return result
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read().decode()[:200]}"
                print(f"[groq] {model} attempt {attempt}: {last}")
                if e.code in (400, 401, 403, 404):
                    break
                time.sleep(4)
            except Exception as e:
                last = str(e)
                print(f"[groq] {model} attempt {attempt}: {last}")
                time.sleep(4)
    raise RuntimeError(f"Groq failed on all models. Last error: {last}")

def gemini_json(prompt):
    key = os.environ["GEMINI_API_KEY"]
    base = "https://generativelanguage.googleapis.com/v1beta"
    req = urllib.request.Request(f"{base}/models?key={key}&pageSize=100")
    listing = json.loads(urllib.request.urlopen(req, timeout=60).read())
    usable = [m["name"].split("/")[-1] for m in listing.get("models", [])
              if "generateContent" in m.get("supportedGenerationMethods", [])
              and "flash" in m["name"] and "embedding" not in m["name"]
              and "image" not in m["name"] and "tts" not in m["name"]
              and "live" not in m["name"] and "native-audio" not in m["name"]]
    if not usable:
        raise RuntimeError(f"No usable Gemini models for this key. Got: {str(listing)[:400]}")
    model = "gemini-flash-latest" if "gemini-flash-latest" in usable else usable[0]
    print(f"[gemini] using model: {model}")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}}
    req = urllib.request.Request(f"{base}/models/{model}:generateContent?key={key}",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        out = json.loads(urllib.request.urlopen(req, timeout=120).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gemini HTTP {e.code}: {e.read().decode()[:500]}")
    return _extract_json(out["candidates"][0]["content"]["parts"][0]["text"])

def llm_json(prompt):
    if os.environ.get("GROQ_API_KEY"):
        try:
            return groq_json(prompt)
        except Exception as e:
            print(f"[llm] Groq failed ({str(e)[:200]}) — trying Gemini backup")
    return gemini_json(prompt)

def cmd_write(ep_id, topic):
    ep = EPS / ep_id
    ep.mkdir(parents=True, exist_ok=True)
    out = ep / "script.json"
    if out.exists():
        print(f"[write] {out} already exists — skipping (idempotent)")
        return
    topic = topic or random.choice(TOPICS)
    print(f"[write] topic: {topic}")
    data = llm_json(WRITER_PROMPT.format(topic=topic,
                                         character=DEFAULT_BIBLE["character"],
                                         style=DEFAULT_BIBLE["style"]))
    for k in ("title", "hook", "caption"):
        data.setdefault(k, "untitled")
    data.setdefault("hashtags", ["#lifeateverylevel", "#ai", "#fyp"])
    if not isinstance(data.get("levels"), list) or not data["levels"]:
        raise RuntimeError(f"script has no levels. Raw keys: {list(data.keys())}")
    for lv in data["levels"]:
        lv.setdefault("label", "Level")
        lv.setdefault("narration", "")
        lv.setdefault("visual", DEFAULT_BIBLE["character"])
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"[write] OK -> {out}")

def cmd_produce(ep_id):
    ep = EPS / ep_id
    sc = json.loads((ep / "script.json").read_text())
    imgs, auds, segs = ep / "images", ep / "audio", ep / "segs"
    for d in (imgs, auds, segs):
        d.mkdir(parents=True, exist_ok=True)
    bible = DEFAULT_BIBLE
    for i, lv in enumerate(sc["levels"], 1):
        out = imgs / f"L{i}.jpg"
        if out.exists() and out.stat().st_size > 10000:
            print(f"[img] L{i} cached"); continue
        prompt = f"{lv['visual']}, {bible['style']}"
        url = IMG_URL.format(p=urllib.parse.quote(prompt), seed=bible["seed"] + i)
        ok = False
        for attempt in range(1, 6):
            try:
                urllib.request.urlretrieve(url, out)
                if out.stat().st_size > 10000:
                    ok = True; break
                print(f"[img] L{i} attempt {attempt}: file too small, retrying")
            except Exception as e:
                print(f"[img] L{i} attempt {attempt}: {e}")
            time.sleep(3)
        if not ok:
            raise RuntimeError(f"image L{i} failed after 5 attempts")
        print(f"[img] L{i} ok")
    for i, lv in enumerate(sc["levels"], 1):
        out = auds / f"L{i}.mp3"
        if out.exists() and out.stat().st_size > 1000:
            print(f"[tts] L{i} cached"); continue
        txt = lv["narration"] if i > 1 else f"{sc['hook']} {lv['narration']}"
        for attempt in range(1, 4):
            try:
                sh(["edge-tts", "--voice", VOICE, "--text", txt, "--write-media", out])
                break
            except Exception as e:
                print(f"[tts] L{i} attempt {attempt}: {e}")
                time.sleep(3)
        else:
            raise RuntimeError(f"narration L{i} failed after 3 attempts")
        print(f"[tts] L{i} ok")
    seg_files = []
    for i, lv in enumerate(sc["levels"], 1):
        sf = segs / f"seg{i}.mp4"
        seg_files.append(sf)
        if sf.exists():
            print(f"[seg] {i} cached"); continue
        a = dur(auds / f"L{i}.mp3")
        frames = int(a * FPS) + FPS
        label = "".join(ch for ch in lv["label"] if ch.isalnum() or ch.isspace()) or f"Level {i}"
        vf = ("scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,"
              f"zoompan=z='min(zoom+0.0015,1.25)':d={frames}:s=720x1280:fps={FPS},"
              f"drawtext=text='{label}':fontcolor=white:fontsize=48:box=1:"
              f"boxcolor=black@0.5:boxborderw=12:x=(w-text_w)/2:y=h-160:fontfile={FONT}")
        try:
            sh(["ffmpeg", "-y", "-loop", "1", "-i", imgs / f"L{i}.jpg", "-i", auds / f"L{i}.mp3",
                "-vf", vf, "-t", f"{a:.2f}", "-r", str(FPS), "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest", sf])
        except Exception:
            if sf.exists():
                sf.unlink()
            raise
        print(f"[seg] {i} ok ({a:.1f}s)")
    lst = ep / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in seg_files))
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
        "-c", "copy", ep / "video.mp4"])
    meta = {"episode": ep_id, "title": sc["title"], "caption": sc["caption"],
            "hashtags": sc["hashtags"],
            "platforms": {"youtube": "private", "tiktok": "draft"},
            "ai_disclosure": "Created with AI tools"}
    (ep / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    size = (ep / "video.mp4").stat().st_size / 1e6
    print(f"[produce] OK -> {ep / 'video.mp4'} ({size:.1f} MB)")

def cmd_notify(ep_id):
    ep = EPS / ep_id
    sc = json.loads((ep / "script.json").read_text())
    text = f"🎬 {sc['title']}\n\n{sc['caption']}\n\n{' '.join(sc['hashtags'])}\n\nepisode: {ep_id}"
    vid = ep / "video.mp4"
    size_mb = vid.stat().st_size / 1e6
    api = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"
    if size_mb >= 49:
        r = requests.post(f"{api}/sendMessage",
                          data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text})
        print(f"[notify] {r.status_code} {r.text[:200]}")
        r.raise_for_status()
        print(f"[notify] video is {size_mb:.0f} MB — download it from the run's Artifacts")
        return
    with open(vid, "rb") as f:
        r = requests.post(f"{api}/sendVideo",
                          data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": text[:1024]},
                          files={"video": f}, timeout=600)
    print(f"[notify] {r.status_code} {r.text[:200]}")
    r.raise_for_status()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["write", "produce", "notify"])
    p.add_argument("--episode", required=True)
    p.add_argument("--topic")
    a = p.parse_args()
    {"write": lambda: cmd_write(a.episode, a.topic),
     "produce": lambda: cmd_produce(a.episode),
     "notify": lambda: cmd_notify(a.episode)}[a.cmd]()
