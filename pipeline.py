"""Faceless 'Life at Every Level' pipeline."""
import argparse, json, os, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).parent
EPS = ROOT / "episodes"
VOICE = "en-US-ChristopherNeural"
FPS = 30
FONT = os.environ.get("FONT", "DejaVuSans")
IMG_URL = ("https://image.pollinations.ai/prompt/{p}"
           "?width=720&height=1280&seed={seed}&model=flux&nologo=true")

def sh(cmd): subprocess.run([str(c) for c in cmd], check=True, capture_output=True, text=True)

def dur(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                                   "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.decode().strip())

DEFAULT_BIBLE = {
    "character": "a kind middle-aged farmer man, short black hair, tan skin, simple beige tunic, weathered hands",
    "style": "cinematic photorealistic, warm golden hour light, rich detail, vertical composition, game concept art quality",
    "negative": "text, watermark, logo, deformed hands, extra limbs, blurry",
    "seed": 777123
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
    order = (["gemini-flash-latest"] if "gemini-flash-latest" in usable else []) + \
            [m for m in usable if m != "gemini-flash-latest"]
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}}
    last_err = None
    for model in order[:4]:
        for attempt in range(3):
            try:
                print(f"[gemini] trying {model} (attempt {attempt+1})")
                req = urllib.request.Request(
                    f"{base}/models/{model}:generateContent?key={key}",
                    data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"})
                out = json.loads(urllib.request.urlopen(req, timeout=120).read())
                print(f"[gemini] OK with model: {model}")
                return json.loads(out["candidates"][0]["content"]["parts"][0]["text"])
            except urllib.error.HTTPError as e:
                last_err = f"Gemini HTTP {e.code}: {e.read().decode()[:300]}"
                print(f"[gemini] {last_err}")
                if e.code in (429, 500, 503):
                    time.sleep(20 * (attempt + 1))
                else:
                    break
            except Exception as e:
                last_err = str(e); print(f"[gemini] {last_err}"); time.sleep(10)
    raise RuntimeError(f"All Gemini models busy/unavailable. Last error: {last_err}")

def cmd_write(name, topic):
    ep = EPS / name; ep.mkdir(parents=True, exist_ok=True)
    bible_p = ep / "character_bible.json"
    if not bible_p.exists():
        bible_p.write_text(json.dumps(DEFAULT_BIBLE, indent=2))
    bible = json.loads(bible_p.read_text())
    prompt = WRITER_PROMPT.format(topic=topic or "a villager's life upgrading at every level",
                                  character=bible["character"], style=bible["style"])
    script = gemini_json(prompt)
    assert len(script.get("levels", [])) == 7, f"expected 7 levels, got {len(script.get('levels', []))}"
    (ep / "script.json").write_text(json.dumps(script, indent=2))
    (ep / "metadata.json").write_text(json.dumps({
        "title": script["title"], "caption": script["caption"],
        "hashtags": " ".join(script["hashtags"]),
        "youtube_visibility": "private",
        "ai_disclosure": "AI-generated imagery and voice",
        "episode": name}, indent=2))
    print(f"[write] OK -> {ep/'script.json'}")

def gen_image(prompt, seed, out: Path):
    if out.exists(): return
    url = IMG_URL.format(p=urllib.parse.quote(prompt), seed=seed)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=180).read()
            if len(data) > 10_000:
                out.write_bytes(data); print(f"[img] {out.name} ({len(data)//1024}KB)"); return
        except Exception as e:
            print(f"[img] retry {attempt+1}: {e}"); time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"image failed: {out.name}")

def tts(text, out: Path):
    if out.exists(): return dur(out)
    for attempt in range(4):
        try:
            sh(["edge-tts", "--voice", VOICE, "--text", text, "--write-media", out])
            return dur(out)
        except Exception as e:
            print(f"[tts] retry {attempt+1}: {e}"); time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"tts failed: {out.name}")

def segment(img: Path, text: str, label: str, wav: Path, out: Path):
    d = dur(wav) + 0.9
    frames = int(d * FPS) + 1
    label = label.replace(":", " ").replace("'", "")
    vf = (f"scale=1440:2560,"
          f"zoompan=z='min(zoom+0.0012,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
          f":d={frames}:s=720x1280:fps={FPS},"
          f"drawtext=font={FONT}:text='{label}':fontsize=52:fontcolor=white:"
          f"borderw=3:x=(w-text_w)/2:y=90:enable='between(t,0,1.4)',"
          f"format=yuv420p")
    sh(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", img, "-i", wav,
        "-filter_complex", f"[0:v]{vf}[v];[1:a]adelay=250:all=1,apad=whole_dur={d}[a]",
        "-map", "[v]", "-map", "[a]", "-t", f"{d:.2f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", out])
    return d

def cmd_produce(name):
    ep = EPS / name
    bible = json.loads((ep / "character_bible.json").read_text())
    script = json.loads((ep / "script.json").read_text())
    imgs, segs, list_f = ep / "images", ep / "segments", ep / "list.txt"
    imgs.mkdir(exist_ok=True); segs.mkdir(exist_ok=True)

    hook_wav = ep / "hook.mp3"
    tts(script["hook"], hook_wav)
    parts = [(imgs / "hook.jpg",
              f"{bible['character']}, {bible['style']}, dramatic establishing shot, mysterious atmosphere",
              "WATCH", hook_wav)]
    for i, lv in enumerate(script["levels"], start=1):
        parts.append((imgs / f"L{i}.jpg",
                      f"{bible['character']}, {bible['style']}, {lv['visual']}, {bible['negative']}",
                      lv["label"], ep / f"nar{i}.mp3"))
        tts(lv["narration"], ep / f"nar{i}.mp3")

    total = 0.0
    for i, (img, prompt, label, wav) in enumerate(parts):
        gen_image(prompt, bible["seed"] + i, img)
        total += segment(img, prompt, label, wav, segs / f"seg{i}.mp4")

    list_f.write_text("".join(f"file '{s.resolve()}'\n" for s in sorted(segs.glob("seg*.mp4"))))
    concat = ep / "concat.mp4"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_f, "-c", "copy", concat])

    bgm = ep / "bgm.mp3"
    final = ep / "video.mp4"
    if bgm.exists():
        sh(["ffmpeg", "-y", "-i", concat, "-stream_loop", "-1", "-i", bgm,
            "-filter_complex", "[1:a]volume=0.12[bg];[0:a][bg]amix=inputs=2:duration=first[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", final])
    else:
        concat.replace(final)

    size = final.stat().st_size
    assert size < 48_000_000, f"video {size/1e6:.1f}MB exceeds Telegram 50MB"
    print(f"[produce] OK -> {final}  ({dur(final):.1f}s, {size/1e6:.1f}MB)")

def cmd_notify(name):
    import requests
    ep = EPS / name
    meta = json.loads((ep / "metadata.json").read_text())
    caption = (f"🎬 {meta['title']}\n\n{meta['caption']}\n\n{meta['hashtags']}\n\n"
               f"EP: {meta['episode']} · visibility: {meta['youtube_visibility']}")
    r = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendVideo",
                      data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": caption[:1024]},
                      files={"video": open(ep / "video.mp4", "rb")}, timeout=600)
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
