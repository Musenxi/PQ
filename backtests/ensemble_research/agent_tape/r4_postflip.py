exec(open('common.py').read())
tp=pd.read_pickle(SP+'tape_feat.pkl'); tp['h']=np.where(tp.start<MED,1,2)
rows=[]
for lo,hi in [(.3,.45),(.3,.5),(.35,.5),(.2,.4)]:
  for T in [20,30,60]:
    for cmin in [1,2]:
      o=tp[(tp.price>=lo)&(tp.price<hi)&(tp.off>=T)&(tp.chop>=cmin)].drop_duplicates('slug')
      rows.append(summ(o,f'postflip underdog [{lo},{hi}) T{T} chop>={cmin}'))
      o=tp[(tp.price>=lo)&(tp.price<hi)&(tp.off>=T)&(tp.chop==0)].drop_duplicates('slug')
      if cmin==1: rows.append(summ(o,f'  control nochop [{lo},{hi}) T{T}'))
R=pd.DataFrame(rows); print(R.round(3).to_string())
# does the post-flip underdog row come with its 'favorite' counterpart? check implied: underdog side price vs winrate
o=tp[(tp.price>=.3)&(tp.price<.45)&(tp.off>=30)&(tp.chop>=1)].drop_duplicates('slug')
print('price',o.price.mean().round(3),'win',o.win.mean().round(3),'n',len(o),'off',o.off.mean().round(1))
# is the underdog the side that was favorite before the flip (fell back) or the side that never led?
print('own side v30 mean',o.v30_o.mean(), 'frac own side was falling', (o.run_o<0).mean())
