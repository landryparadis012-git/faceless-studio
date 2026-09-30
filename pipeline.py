"""Faceless series studio v6. Groq + Gemini backup. Cloudflare images. Series memory. Limit auto-resume."""
import argparse, base64, datetime, json, os, random, socket, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path
import requests

socket.setdefaulttimeout(120)
ROOT = Path(__file__).parent
EPS = ROOT / "episodes"
VOICE = "en-US-ChristopherNeural"
FPS = 30
FONT = os.environ.get("FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
GROQ = "https://api.groq.com/openai/v1/chat/completions"
GROQ_UA = "faceless-studio/1.0"
GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
MAX_EPISODES = 8

class DailyLimitError(Exception):
    pass

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
    "character": "a 45-year-old farmer man, weathered olive-tan skin, kind deep-set brown eyes, short black hair with gray at the temples, thick eyebrows, a small scar over his left eyebrow, wearing a patched beige linen tunic and a worn copper amulet on a leather cord, mud-flecked leather boots",
    "style": "cinematic photorealistic period drama still, shot on 85mm lens, shallow depth of field, volumetric golden-hour light with soft god rays, rich film grain, deep teal and amber color grade, hyper-detailed skin and fabric textures, dramatic composition, prestige TV quality, vertical 9:16 framing",
    "negative": "text, watermark, logo, deformed hands, extra limbs, blurry, cartoonish, plastic skin",
    "seed": 777123,
}

WRITER_PROMPT = """You write viral TikTok series episodes in the "life at every level" style — cinematic, emotionally gripping, engineered for watch-time.
{memory}

CHARACTER (the EXACT string below must be repeated VERBATIM at the start of EVERY single visual, so the face never changes):
{character}

STYLE (append to the end of every visual): {style}

Structure: 7 levels (Level 1, 2, 5, 10, 25, 50, 100), each level has EXACTLY 2 shots —
shot A = arrival (stepping into the stage), shot B = payoff (a win, a shock, or a lesson).
That is EXACTLY 14 shots.

EVERY visual must be a rich cinematic painting description: the verbatim character string, plus the emotion on the face, a specific physical action, and at least 3 concrete environment details (objects, weather, crowd, textures). Vary the camera like a director: extreme close-up for emotional beats, wide establishing shot for arrivals, low-angle for power moments, over-the-shoulder for confrontations.

Narration: 17-22 vivid storytelling words per shot, ONE continuous story across all 14. Part 1 must open with a 3-second pattern-interrupt hook (a shocking statement or question), never a slow intro.

ENGAGEMENT ENDING (mandatory): the final shot's narration must end with ONE of these patterns, rotated between episodes: a cliffhanger question the viewer must answer (like: Will the king finally agree? or: Who is really behind the signal?); a next-part promise (like: Part 5 tomorrow — follow so you do not miss what happens); or a comment-bait challenge (like: Comment FORGIVE if you would let her stay).

Return ONLY valid JSON, no markdown:
{{"title": "<series name + Episode number, <=60 chars>",
  "hook": "<opening narration line, <=15 words>",
  "levels": [
    {{"label": "Part 1",  "narration": "<17-22 vivid words>", "visual": "<verbatim character string + emotion + action + 3+ environment details + camera angle>"}},
    {{"label": "Part 2",  "narration": "...", "visual": "..."}},
    {{"label": "Part 3",  "narration": "...", "visual": "..."}},
    {{"label": "Part 4",  "narration": "...", "visual": "..."}},
    {{"label": "Part 5",  "narration": "...", "visual": "..."}},
    {{"label": "Part 6",  "narration": "...", "visual": "..."}},
    {{"label": "Part 7",  "narration": "...", "visual": "..."}},
    {{"label": "Part 8",  "narration": "...", "visual": "..."}},
    {{"label": "Part 9",  "narration": "...", "visual": "..."}},
    {{"label": "Part 10", "narration": "...", "visual": "..."}},
    {{"label": "Part 11", "narration": "...", "visual": "..."}},
    {{"label": "Part 12", "narration": "...", "visual": "..."}},
    {{"label": "Part 13", "narration": "...", "visual": "..."}},
    {{"label": "Part 14", "narration": "...<ends with the engagement hook>", "visual": "<verbatim character string + emotion + action + 3+ details + camera angle + cliffhanger image>"}}
  ],
  "caption": "<under 150 chars: bold statement or question + which Part this is + follow CTA>",
  "hashtags": ["#lifeateverylevel", "#villagelife", "#ai", "#fyp", "<series name as one lowercase word with #>", "<story hashtag>"],
  "memory": {{"series_title": "<series name>", "this_episode_recap": "<3-4 sentences: what happened in THIS episode>", "ending_cliffhanger": "<exact cliffhanger the next episode must resolve>", "ending_pattern_used": "<which of: cliffhanger question, next-part promise, comment-bait>"}}}}
Rules: environment escalates mud hut -> palace/city; visuals always describe the SAME person; no real brands or real people."""

def _extract_json(txt):
    txt = txt.strip()
    i, j = txt.find("{"), txt.rfind("}")
    if i == -1 or j == -1:
        raise ValueError(f"no JSON object found in: {txt[:200]}")
    return json.loads(txt[i:j + 1])

def _groq_call_curl(model, prompt, key):
    payload = json.dumps({"model": model,
                          "messages": [{"role": "user", "content": prompt}],
                          "response_format": {"type": "json_object"},
                          "max_completion_tokens": 6000,
                          "temperature": 1.0})
    p = subprocess.run(["curl", "-s", "-w", "\n%{http_code}", "--max-time", "120",
                        "-X", "POST", GROQ,
                        "-H", f"Authorization: Bearer {key}",
                        "-H", "Content-Type: application/json",
                        "-d", payload],
                       capture_output=True, text=True, timeout=150)
    if p.returncode != 0:
        raise RuntimeError(f"curl transport error: {p.stderr[:150]}")
    body, _, code = p.stdout.rpartition("\n")
    if code.strip() != "200":
        raise RuntimeError(f"curl HTTP {code.strip()}: {body[:150]}")
    out = json.loads(body)
    return _extract_json(out["choices"][0]["message"]["content"])

def groq_json(prompt):
    key = os.environ["GROQ_API_KEY"]
    last = None
    for model in GROQ_MODELS:
        blocked = False
        for attempt in range(1, 4):
            try:
                print(f"[groq] trying {model} (attempt {attempt}/3)")
                body = {"model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "response_format": {"type": "json_object"},
                        "max_completion_tokens": 6000,
                        "temperature": 1.0}
                req = urllib.request.Request(
                    GROQ, data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {key}",
                             "User-Agent": GROQ_UA})
                out = json.loads(urllib.request.urlopen(req, timeout=120).read())
                result = _extract_json(out["choices"][0]["message"]["content"])
                print(f"[groq] OK via {model}")
                return result
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read().decode()[:200]}"
                print(f"[groq] {model} attempt {attempt}: {last}")
                if e.code in (400, 401, 404):
                    break
                if e.code == 403:
                    blocked = True
                    break
                time.sleep(4)
            except Exception as e:
                last = str(e)
                print(f"[groq] {model} attempt {attempt}: {last}")
                time.sleep(4)
        if blocked:
            try:
                print(f"[groq] firewall blocked Python — trying curl for {model}")
                result = _groq_call_curl(model, prompt, key)
                print(f"[groq] OK via curl ({model})")
                return result
            except Exception as e:
                last = str(e)
                print(f"[groq] curl {model}: {last}")
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
    last = None
    for attempt in range(1, 5):
        try:
            print(f"[gemini] attempt {attempt}/4")
            req = urllib.request.Request(f"{base}/models/{model}:generateContent?key={key}",
                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            out = json.loads(urllib.request.urlopen(req, timeout=120).read())
            return _extract_json(out["candidates"][0]["content"]["parts"][0]["text"])
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:300]}"
            print(f"[gemini] attempt {attempt}: {last}")
            if e.code not in (429, 500, 502, 503, 504):
                raise
            if attempt < 4:
                time.sleep(25)
        except Exception as e:
            last = str(e)
            print(f"[gemini] attempt {attempt}: {last}")
            if attempt < 4:
                time.sleep(25)
    raise RuntimeError(f"Gemini failed after 4 attempts. Last: {last}")

def llm_json(prompt):
    try:
        return groq_json(prompt)
    except Exception as e:
        print(f"[llm] Groq failed: {e} — trying Gemini backup")
    return gemini_json(prompt)

def gen_image(prompt, out):
    acct = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    key = os.environ["CLOUDFLARE_API_TOKEN"]
    print(f"[img] using account id: {acct[:4]}... ({len(acct)} chars)")
    models = [
        ("flux", "@cf/black-forest-labs/flux-1-schnell",
         {"prompt": prompt, "steps": 4}),
        ("sdxl", "@cf/stabilityai/stable-diffusion-xl-base-1.0",
         {"prompt": prompt, "width": 576, "height": 1024}),
    ]
    last = None
    limit_hits = 0
    for name, model, body in models:
        for attempt in range(1, 4):
            try:
                print(f"[img] {name} attempt {attempt}/3")
                req = urllib.request.Request(
                    f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}",
                    data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {key}"})
                resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
                if not resp.get("success"):
                    raise ValueError(f"API error: {str(resp)[:150]}")
                img_b64 = resp.get("result", {}).get("image")
                if not img_b64:
                    raise ValueError(f"no image in response: {str(resp)[:150]}")
                with open(out, "wb") as f:
                    f.write(base64.b64decode(img_b64))
                if out.stat().st_size > 10000:
                    print(f"[img] OK via {name}")
                    return
                raise ValueError("image file too small")
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read().decode()[:200]}"
                print(f"[img] {name} attempt {attempt}: {last}")
                low = last.lower()
                is_daily = (e.code == 402 or
                            (e.code == 429 and any(k in low for k in ("daily", "limit", "quota", "neuron"))))
                if is_daily:
                    limit_hits += 1
                    if limit_hits >= 2:
                        raise DailyLimitError(f"Cloudflare free daily limit reached. Last: {last[:150]}")
                elif e.code in (401, 403, 404):
                    break
                if attempt < 3:
                    time.sleep(5)
            except Exception as e:
                last = str(e)
                print(f"[img] {name} attempt {attempt}: {last}")
                if attempt < 3:
                    time.sleep(5)
            finally:
                if out.exists() and out.stat().st_size <= 10000:
                    out.unlink()
    raise RuntimeError(f"image generation failed for {out.name}. Last: {last}")

def load_state():
    f = ROOT / "memory" / "series_state.json"
    try:
        return json.loads(f.read_text())
    except FileNotFoundError:
        return None
    except Exception:
        bak = f.with_suffix(".json.bak")
        print(f"[memory] memory file unreadable — archiving it and starting a fresh series")
        try:
            f.rename(bak)
        except Exception:
            pass
        return None

def cmd_write(ep_id, topic):
    ep = EPS / ep_id
    ep.mkdir(parents=True, exist_ok=True)
    out = ep / "script.json"
    if out.exists():
        print(f"[write] {out} already exists — skipping (idempotent)")
        return
    st = load_state()
    if st and not st.get("finished") and st.get("episode_number", 0) < MAX_EPISODES:
        n = st["episode_number"] + 1
        memory_text = (f"CONTINUING SERIES '{st['series_title']}' — Episode {n} of {MAX_EPISODES}.\n"
                       f"Recap of episode {st['episode_number']}: {st.get('last_recap', '')}\n"
                       f"It ended on this cliffhanger: {st.get('ending_cliffhanger', '')}\n"
                       "Continue the SAME story with the SAME characters. Do NOT start over.")
        if st.get("last_hook"):
            memory_text += (f"\nLast episode ended with this hook pattern: {st['last_hook']}. "
                            "Use a DIFFERENT one of the three patterns this time.")
    else:
        n = 1
        memory_text = ("START A BRAND NEW SERIES (nothing exists yet). Invent a fresh premise, "
                       f"characters and series title. It will run {MAX_EPISODES} episodes, "
                       "so plant seeds for future growth.")
    if topic:
        memory_text += f"\nCreator's brief (follow it): {topic}"
    print(f"[write] episode #{n} of series")
    data = None
    last_err = None
    for attempt in range(1, 4):
        try:
            probe = memory_text
            if last_err:
                probe += (f"\nIMPORTANT: your previous answer was rejected ({last_err}). "
                          "Return ALL 14 shots AND the complete memory object.")
            data = llm_json(WRITER_PROMPT.format(memory=probe,
                                                 character=DEFAULT_BIBLE["character"],
                                                 style=DEFAULT_BIBLE["style"]))
            if isinstance(data.get("levels"), list) and 10 <= len(data["levels"]) <= 16:
                break
            last_err = f"only {len(data.get('levels', []))} shots"
            data = None
        except Exception as e:
            last_err = str(e)[:150]
            data = None
    if data is None:
        raise RuntimeError(f"script writer failed after 3 attempts. Last problem: {last_err}")
    for k in ("title", "hook", "caption"):
        data.setdefault(k, "untitled")
    data.setdefault("hashtags", ["#lifeateverylevel", "#ai", "#fyp"])
    for lv in data["levels"]:
        lv.setdefault("label", "Part")
        lv.setdefault("narration", "")
        lv.setdefault("visual", DEFAULT_BIBLE["character"])
    mem = data.get("memory", {}) if isinstance(data.get("memory"), dict) else {}
    if not mem:
        print("[memory] model omitted the memory object — rebuilding it from the script")
        all_narr = " ".join(lv["narration"] for lv in data["levels"])
        mem = {"series_title": str(data.get("title") or "Untitled Series")[:120],
               "this_episode_recap": all_narr[:600],
               "ending_cliffhanger": data["levels"][-1]["narration"][:400],
               "ending_pattern_used": ""}
    st2 = {"series_title": str(mem.get("series_title") or data.get("title") or "Untitled Series")[:120],
           "episode_number": n,
           "last_recap": str(mem.get("this_episode_recap", ""))[:600],
           "ending_cliffhanger": str(mem.get("ending_cliffhanger", ""))[:400],
           "last_hook": str(mem.get("ending_pattern_used", ""))[:60],
           "finished": n >= MAX_EPISODES}
    (ROOT / "memory").mkdir(exist_ok=True)
    (ROOT / "memory" / "series_state.json").write_text(json.dumps(st2, indent=2, ensure_ascii=False))
    print(f"[memory] episode {n}/{MAX_EPISODES} recorded" + (" — SERIES COMPLETE! next /start = new series" if st2["finished"] else ""))
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
        out = imgs / f"L{i}.png"
        if out.exists() and out.stat().st_size > 10000:
            print(f"[img] L{i} cached"); continue
        prompt = f"{lv['visual']}, {bible['style']}"
        gen_image(prompt, out)
        print(f"[img] L{i} ok")
    for i, lv in enumerate(sc["levels"], 1):
        out = auds / f"L{i}.mp3"
        if out.exists() and out.stat().st_size > 1000:
            print(f"[tts] L{i} cached"); continue
        txt = lv["narration"]
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
        label = "".join(ch for ch in lv["label"] if ch.isalnum() or ch.isspace()) or f"Part {i}"
        vf = ("scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,"
              f"zoompan=z='min(zoom+0.0015,1.25)':d={frames}:s=720x1280:fps={FPS},"
              f"drawtext=text='{label}':fontcolor=white:fontsize=48:box=1:"
              f"boxcolor=black@0.5:boxborderw=12:x=(w-text_w)/2:y=h-160:fontfile={FONT}")
        try:
            sh(["ffmpeg", "-y", "-loop", "1", "-i", imgs / f"L{i}.png", "-i", auds / f"L{i}.mp3",
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
    text = f"🎬 {sc['title']}\n\n{sc.get('hook', '')}\n\n{sc['caption']}\n\n{' '.join(sc['hashtags'])}\n\nepisode: {ep_id}"
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

def _tell(text):
    try:
        requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                      data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text[:4000]}, timeout=60)
    except Exception:
        pass

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["write", "produce", "notify"])
    p.add_argument("--episode", required=True)
    p.add_argument("--topic")
    a = p.parse_args()
    try:
        {"write": lambda: cmd_write(a.episode, a.topic),
         "produce": lambda: cmd_produce(a.episode),
         "notify": lambda: cmd_notify(a.episode)}[a.cmd]()
    except DailyLimitError:
        now = datetime.datetime.now(datetime.timezone.utc)
        reset = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        hrs = (reset - now).total_seconds() / 3600
        reset_s = reset.strftime("%Y-%m-%d %H:%M UTC")
        open("/tmp/limit_flag.txt", "w").write(reset.strftime("%Y-%m-%dT%H:%M:%SZ"))
        print(f"[limit] daily free limit hit — resets {reset_s} (~{hrs:.0f}h)")
        _tell(f"🛑 Daily free limit reached.\n\nResets at {reset_s} (in ~{hrs:.0f}h).\n\nThe next episode will AUTO-RETRY about an hour after reset — nothing is lost. No need to /start (but you can if you're impatient).")
        sys.exit(1)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        _tell(f"❌ run failed ({a.cmd})\n\n{tb[-2500:]}")
        sys.exit(1)
