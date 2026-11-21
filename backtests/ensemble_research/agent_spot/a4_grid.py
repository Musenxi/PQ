"""Item 4: buy the spot-favoured side, grid |spot-open| ($, reconstructed) x tau."""
exec(open('common.py').read())
f=t.dropna(subset=['fair','sig']).copy()
f=f[f.tau>=20]
f['adist']=f.dist.abs()
f['db']=pd.cut(f.adist,[0,10,25,50,100,1e5],right=False)
f['tb']=pd.cut(f.tau,[20,120,180,240,290],right=False)
# exact: traded side is spot-favoured
ex=f[f.z_side>0]
# approx: non-favoured rows converted: fav ask ~= 1-(price-0.01)
ap=f[f.z_side<=0].copy(); ap['price']=(1.01-ap.price).clip(0.02,0.98); ap['win']=1-ap.win
ap['fee7']=0.07*ap.price*(1-ap.price); ap['ret']=(ap.win-ap.price-ap.fee7)/ap.price
both=pd.concat([ex,ap])
for name,df in [('EXACT',ex),('EXACT+APPROX',both)]:
    print('=====',name)
    for (d,tb),q in df.groupby(['db','tb'],observed=True):
        q1=q.sort_values('tsec').drop_duplicates('slug')
        if q1.slug.nunique()<20: continue
        r=report(q1,f'|d|={d} tau={tb} px={q1.price.mean():.2f}')
