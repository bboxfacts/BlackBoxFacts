# ============================================================ CLI (keep as-is) =====
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    if mode == "frames":
        os.makedirs("preview", exist_ok=True)
        for arg in sys.argv[2:]:
            render(float(arg)).save(f"preview/t_{float(arg):07.2f}.png")
    elif mode == "sheet":
        ts = [float(a) for a in sys.argv[3:]]
        cols = 3
        tw, th = 360, 640
        rows = math.ceil(len(ts) / cols)
        sheet = Image.new("RGB", (cols * tw + (cols + 1) * 8, rows * th + (rows + 1) * 8), (40, 40, 40))
        for k, tt in enumerate(ts):
            im = render(tt).resize((tw, th), Image.LANCZOS)
            sheet.paste(im, (8 + (k % cols) * (tw + 8), 8 + (k // cols) * (th + 8)))
        sheet.save(sys.argv[2])
    elif mode == "part":
        a, b, outp = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
        b = min(b, int(math.ceil(TOTAL * FPS)))
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
               "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
               "-pix_fmt", "yuv420p", outp]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        t0 = time.time()
        for k in range(a, b):
            p.stdin.write(render(k / FPS).tobytes())
        p.stdin.close(); p.wait()
        print(f"frames {a}-{b} done in {time.time() - t0:.0f}s", flush=True)
    elif mode == "bench":
        t0 = time.time()
        for k in range(20):
            render(min(TOTAL - 0.1, 5 + k * (TOTAL / 25)))
        print("sec/frame:", (time.time() - t0) / 20)
    else:  # full -- fine for quick local tests; use `part` x N for the real deliverable
        n = int(math.ceil(TOTAL * FPS))
        print("frames:", n, "duration:", TOTAL, flush=True)
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
               "-r", str(FPS), "-i", "-", "-i", "audio/vo.mp3", "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "out.mp4"]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for k in range(n):
            p.stdin.write(render(k / FPS).tobytes())
        p.stdin.close(); p.wait()
        print("done", flush=True)
