"""Item 2: TWAP vs close-print disagreement."""
exec(open('common.py').read())
w=ss.copy(); w['sp']=np.where(w.close>=w.open,'Up','Down'); w['dis']=w.sp!=w.winner
w['ad']=w.d.abs()
print('disagree rate',w.dis.mean().round(3),'n',len(w))
# by |d| in units of sigma*open*sqrt(60) (TWAP-window scale)
w['sc']=w.ad/(w.sig_imp*w.open*np.sqrt(60))
print(w.groupby(pd.qcut(w.sc,5),observed=True).dis.agg(['mean','size']))
print('official Up rate',(w.winner=='Up').mean().round(3),' close-print Up rate',(w.sp=='Up').mean().round(3))
print('in disagreement windows official Up share', (w[w.dis].winner=='Up').mean().round(3), 'n',w.dis.sum())
# Note: settlement close print — at exact end? Up if close>=open; ties?
print('ties', (w.d==0).sum())
# late ticks: spot sign (z_side) at tau in [20,100) vs official and close-print
L=t.dropna(subset=['fair']).copy(); L=L[(L.tau<100)]
L=L.sort_values('tau').drop_duplicates('slug')  # latest tick per window
L['up_z']=np.where(L.z_side>0,L.side,np.where(L.side=='Up','Down','Up'))
L=L.join(w[['sp','dis','ad']],on='start')
print('\nlatest tick tau<100: n',len(L),'agree official',(L.up_z==L.winner).mean().round(3),'agree closeprint',(L.up_z==L.sp).mean().round(3))
cc=L[L.ad<30]
print('close calls |d|<30: n',len(cc),'agree official',(cc.up_z==cc.winner).mean().round(3),'agree closeprint',(cc.up_z==cc.sp).mean().round(3))
dd=L[L.dis]
print('disagree windows: n',len(dd),'spot-sign agrees official',(dd.up_z==dd.winner).mean().round(3))
# does the traded side's price at late tick better predict official or close-print?
L['p_up']=np.where(L.side=='Up',L.price,1-L.price)
for tgt in ['winner','sp']:
    y=(L[tgt]=='Up').astype(float); print(tgt,'brier of late p_up',np.mean((L.p_up-y)**2).round(4))
y1=(cc.winner=='Up').astype(float); y2=(cc.sp=='Up').astype(float); pu=np.where(cc.side=='Up',cc.price,1-cc.price)
print('close-call brier official',np.mean((pu-y1)**2).round(4),'closeprint',np.mean((pu-y2)**2).round(4))
# predictability pre-entry: does prior-window disagreement / low tvol predict disagreement? (not tradable anyway without side)
w['prevdis']=w.dis.shift(1)
print(w.groupby('prevdis').dis.mean())
# key: in disagreement windows who wins relative to the 5m spot direction mid-window? expectation: official follows TWAP i.e. last-60s mean
