from common import *
t,s,W=load_1h()
x=t[(t.family=='FAIR')].copy(); x['r01']=ret(x.win,x.price,x.tsec,r=.01)
x=x.sort_values('tsec').drop_duplicates('slug')   # first FAIR entry per window (any band)
x['early']=x.off<300; x['inb']=(x.price>=.5)&(x.price<=.75)
print(x.groupby(['early','inb']).agg(n=('r01','size'),r=('r01','mean'),wr=('win','mean'),px=('price','mean'),stale=('would_reject','mean'),age=('book_age_ms','median'),gap=('gap','mean'),basis=('basis','mean')).round(3))
e=x[x.early&x.inb]
for k,g in e.groupby('would_reject'): print('would_reject',k,fmt(cboot(g,'r01')))
# side bias? Up vs Down
for k,g in e.groupby('side'): print('side',k,fmt(cboot(g,'r01')))
# |basis|>5 vs small: basis-driven fair?
for k,g in e.groupby(e.basis.abs()>5): print('|basis|>5',k,fmt(cboot(g,'r01')))
