# -*- coding: utf-8 -*-
"""Generates the QuantSim pricing and unit-economics document, charts included."""
import io, math

TEAL   = "#00806a"   # QuantSim highlight, validated: chroma 0.10+, contrast >= 3:1
GREY   = "#8a949e"   # competitor context, deliberately neutral
S1,S2,S3,S4 = "#2a78d6","#eb6834","#1baf7a","#eda100"   # validated categorical slots 1-4
INK,INK2,INK3 = "#12171c","#3f4a55","#6f7b87"
RULE = "#d8dee4"

def esc(t): return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

# ---------------------------------------------------------------- chart 1
def chart_prices():
    rows=[("QuantSim Free",0,True,None),("QuantSim Team, per seat",18,True,None),
          ("QuantRocket, lowest paid",20,False,None),
          ("QuantConnect Team, per seat",24,False,None),
          ("QuantSim Pro",30,True,None),
          ("QuantConnect Trading Firm",48,False,None),
          ("QuantSim Institution, per seat",60,True,None),
          ("QuantConnect Researcher",60,False,None),
          ("QuantConnect Institution",96,False,None),
          ("SimCorp One / AlgoTrader",None,False,"quote only, no public price")]
    L,R,RH,TOP=232,58,31,34; W=920; H=TOP+len(rows)*RH+26
    bw=W-L-R; sc=bw/100.0
    o=[f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Monthly price per seat, QuantSim against competitors, US dollars">']
    o.append(f'<text x="0" y="14" class="ct">Monthly price per seat</text>')
    o.append(f'<text x="0" y="29" class="cs">QuantSim in teal. Lower is cheaper. Institutional competitors publish no price.</text>')
    for g in range(0,101,20):                                   # recessive gridlines
        x=L+g*sc
        o.append(f'<line x1="{x:.1f}" y1="{TOP+4}" x2="{x:.1f}" y2="{TOP+len(rows)*RH}" stroke="{RULE}" stroke-width="1"/>')
        o.append(f'<text x="{x:.1f}" y="{TOP+len(rows)*RH+16}" class="cx">${g}</text>')
    for i,(lab,v,mine,note) in enumerate(rows):
        y=TOP+i*RH+6; bh=15
        o.append(f'<text x="{L-10}" y="{y+12}" class="cl{" b" if mine else ""}">{esc(lab)}</text>')
        if v is None:
            o.append(f'<rect x="{L}" y="{y}" width="{bw}" height="{bh}" rx="4" fill="{GREY}" opacity="0.16"/>')
            o.append(f'<text x="{L+10}" y="{y+12}" class="cn" fill="{INK3}">{esc(note)}</text>')
            continue
        w=max(v*sc,2 if v else 0); c=TEAL if mine else GREY
        if v: o.append(f'<rect x="{L}" y="{y}" width="{w:.1f}" height="{bh}" rx="4" fill="{c}"><title>{esc(lab)}: ${v}/month</title></rect>')
        o.append(f'<text x="{L+w+8:.1f}" y="{y+12}" class="cn{" b" if mine else ""}">${v}</text>')
    o.append('</svg>')
    return "\n".join(o)

# ---------------------------------------------------------------- chart 2
def chart_dollar(scales):
    segs=[("Infrastructure",S1),("Payment processing",S2),("Maintenance",S3),("Net profit",S4)]
    L,R,RH,TOP=96,20,46,58; W=920; H=TOP+len(scales)*RH+10
    bw=W-L-R
    o=[f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Where every dollar of revenue goes, by user count">']
    o.append('<text x="0" y="14" class="ct">Where every dollar of revenue goes</text>')
    o.append('<text x="0" y="29" class="cs">Percentage of monthly revenue. The 10,000-user step is the squeeze: maintenance arrives before revenue does.</text>')
    lx=L
    for name,c in segs:                                          # legend
        o.append(f'<rect x="{lx}" y="{TOP-19}" width="9" height="9" rx="2" fill="{c}"/>')
        o.append(f'<text x="{lx+13}" y="{TOP-11}" class="cx">{esc(name)}</text>')
        lx+=len(name)*6.1+34
    for i,s in enumerate(scales):
        y=TOP+i*RH+4; bh=26; x=L; rev=s["rev"]
        o.append(f'<text x="{L-10}" y="{y+17}" class="cl b">{esc(s["label"])}</text>')
        parts=[("Infrastructure",s["infra"],S1),("Payment processing",s["stripe"],S2),
               ("Maintenance",s["opex"],S3),("Net profit",s["net"],S4)]
        for name,val,c in parts:
            pct=val/rev*100 if rev else 0
            w=pct/100*bw
            if w<=0: continue
            o.append(f'<rect x="{x:.1f}" y="{y}" width="{max(w-2,1):.1f}" height="{bh}" rx="3" fill="{c}">'
                     f'<title>{esc(s["label"])} — {esc(name)}: {pct:.1f}% of revenue, ${val:,.0f}/month</title></rect>')
            if pct>=8:
                o.append(f'<text x="{x+w/2-1:.1f}" y="{y+17}" class="cin">{pct:.0f}%</text>')
            x+=w
        o.append(f'<text x="{L-10}" y="{y+30}" class="cx2">${rev:,.0f}/mo revenue</text>')
    o.append('</svg>')
    return "\n".join(o)

# ---------------------------------------------------------------- chart 3
def chart_modules(mods,batch):
    L,R,RH,TOP=248,130,31,50; W=920; H=TOP+len(mods)*RH+24
    bw=W-L-R; sc=bw/40.0
    o=[f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Share of batch compute by analysis module">']
    o.append('<text x="0" y="14" class="ct">Which module eats the compute</text>')
    o.append('<text x="0" y="29" class="cs">Share of batch compute for a representative run, and the monthly bill it produces at 10,000 users.</text>')
    for g in range(0,41,10):
        x=L+g*sc
        o.append(f'<line x1="{x:.1f}" y1="{TOP}" x2="{x:.1f}" y2="{TOP+len(mods)*RH-6}" stroke="{RULE}" stroke-width="1"/>')
        o.append(f'<text x="{x:.1f}" y="{TOP+len(mods)*RH+10}" class="cx">{g}%</text>')
    for i,(name,pct,mins) in enumerate(mods):
        y=TOP+i*RH-6; bh=16; w=pct*sc
        o.append(f'<text x="{L-10}" y="{y+13}" class="cl">{esc(name)}</text>')
        o.append(f'<rect x="{L}" y="{y}" width="{w:.1f}" height="{bh}" rx="4" fill="{S1}">'
                 f'<title>{esc(name)}: {pct}% of compute, {mins} vCPU-min per run, ${batch*pct/100:,.0f}/month</title></rect>')
        o.append(f'<text x="{L+w+8:.1f}" y="{y+13}" class="cn b">{pct}%</text>')
        o.append(f'<text x="{W}" y="{y+13}" class="cnr" fill="{INK3}">${batch*pct/100:,.0f}/mo</text>')
    o.append('</svg>')
    return "\n".join(o)


# ---------------------------------------------------------------- chart 4
CAT={"Analysis":S1,"Serving":S2,"Fixed":S3}
def chart_all(rows):
    L,R,RH,TOP=252,118,26,60; W=920; H=TOP+len(rows)*RH+22
    bw=W-L-R; top=max(v for _,_,v in rows); sc=bw/800.0
    o=[f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Monthly infrastructure cost by module at ten thousand users">']
    o.append('<text x="0" y="14" class="ct">Every module, by what it costs to run</text>')
    o.append('<text x="0" y="29" class="cs">Monthly infrastructure at 10,000 users. Analysis modules run on the batch fleet; serving modules run on the application tier; fixed lines cost the same whatever the user count.</text>')
    lx=L
    for name,c in CAT.items():
        lab={"Analysis":"Analysis compute","Serving":"Serving tier","Fixed":"Fixed platform"}[name]
        o.append(f'<rect x="{lx}" y="{TOP-21}" width="9" height="9" rx="2" fill="{c}"/>')
        o.append(f'<text x="{lx+13}" y="{TOP-13}" class="cx">{esc(lab)}</text>')
        lx+=len(lab)*6.1+34
    for g in range(0,801,200):
        x=L+g*sc
        o.append(f'<line x1="{x:.1f}" y1="{TOP-4}" x2="{x:.1f}" y2="{TOP+len(rows)*RH-8}" stroke="{RULE}" stroke-width="1"/>')
        o.append(f'<text x="{x:.1f}" y="{TOP+len(rows)*RH+8}" class="cx">${g}</text>')
    for i,(name,cat,val) in enumerate(rows):
        y=TOP+i*RH-6; bh=14; w=val*sc
        o.append(f'<text x="{L-10}" y="{y+12}" class="cl">{esc(name)}</text>')
        o.append(f'<rect x="{L}" y="{y}" width="{w:.1f}" height="{bh}" rx="4" fill="{CAT[cat]}">'
                 f'<title>{esc(name)} — {esc(cat)}: ${val:,}/month, {val/3773*100:.1f}% of infrastructure</title></rect>')
        o.append(f'<text x="{W}" y="{y+12}" class="cnr">${val:,}/mo</text>')
    o.append('</svg>')
    return chr(10).join(o)

ALL=[("Market data ingestion and licensing","Fixed",780),
     ("Monte Carlo path generation","Analysis",724),
     ("TDA persistent homology","Analysis",452),
     ("Dashboard and delivery","Serving",430),
     ("ML risk scoring and retrain","Analysis",326),
     ("Observability and backups","Fixed",183),
     ("Explainability attribution","Analysis",181),
     ("Platform, auth and gateway","Serving",180),
     ("Portfolio and positions","Serving",150),
     ("Alerts and event bus","Serving",120),
     ("Trading strategy evaluation","Serving",95),
     ("Stress scenario batch","Analysis",90),
     ("Composite risk scoring","Analysis",36),
     ("Administration and RBAC","Serving",26)]

# ---------------------------------------------------------------- data
SCALES=[dict(label="100",     rev=150,    infra=0,     stripe=6,     opex=0,      net=144),
        dict(label="1,000",   rev=2460,   infra=485,   stripe=93,    opex=500,    net=1382),
        dict(label="10,000",  rev=33900,  infra=3773,  stripe=1204,  opex=18000,  net=10923),
        dict(label="100,000", rev=339000, infra=26510, stripe=12036, opex=120000, net=180454)]
MODS=[("Monte Carlo path generation",40,24.0),("TDA persistent homology",25,15.0),
      ("ML risk scoring and retrain",18,10.8),("Explainability attribution",10,6.0),
      ("Stress scenario batch",5,3.0),("Composite risk and alerting",2,1.2)]

C1,C2,C3 = chart_prices(), chart_dollar(SCALES), chart_modules(MODS,1810)
C4 = chart_all(ALL)
assert sum(v for _,_,v in ALL) == 3773, sum(v for _,_,v in ALL)
io.open("charts.frag","w",encoding="utf-8").write(("\n@@@\n").join([C1,C2,C3,C4]))
print("charts generated", len(C1), len(C2), len(C3), len(C4))
