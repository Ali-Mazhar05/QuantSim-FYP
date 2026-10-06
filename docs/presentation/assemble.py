import io, re, os
D = r"C:\Users\YM\Desktop\QuantSim\QuantSim\presentation"
charts = io.open(os.path.join(D, "charts.frag"), encoding="utf-8").read().split("\n@@@\n")
s = io.open(os.path.join(D, "doc_shell.html"), encoding="utf-8").read()
for i, c in enumerate(charts, 1):
    s = s.replace("{{CHART%d}}" % i, c)
assert "{{" not in s, re.findall(r"\{\{\w+\}\}", s)
out = os.path.join(D, "QuantSim-Pricing-and-Unit-Economics.html")
io.open(out, "w", encoding="utf-8").write(s)

for name, svg in zip(("prices", "dollar", "modules", "all-modules"), charts):
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    xs = [float(m) for m in re.findall(r'[ ](?:x|x1|x2)="([-\d.]+)"', svg)]
    ys = [float(m) for m in re.findall(r'[ ](?:y|y1|y2)="([-\d.]+)"', svg)]
    ok = "OK" if max(xs) <= vb[2] and max(ys) <= vb[3] else "OVERFLOW"
    print(f"{name:12} {vb[2]:.0f}x{vb[3]:.0f}  x max {max(xs):.0f}  y max {max(ys):.0f}  {ok}")
print("written", len(s), "bytes")
