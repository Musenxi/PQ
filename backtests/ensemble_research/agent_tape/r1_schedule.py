exec(open('common.py').read())
bands=[(.3,.5),(.5,.6),(.55,.75),(.6,.75),(.6,.8),(.65,.85),(.7,.9),(.75,.95),(.5,.95)]
rows=[]
for T in [15,30,45,60,90,120]:
    for mode in ['first','firstinband']:
        g=tp[(tp.off>=T)&(tp.off<T+30)]
        for lo,hi in bands:
            if mode=='first':
                f=g.drop_duplicates('slug'); f=f[(f.price>=lo)&(f.price<hi)]
            else:
                f=g[(g.price>=lo)&(g.price<hi)].drop_duplicates('slug')
            rows.append(summ(f,f'{mode} T{T} [{lo},{hi})'))
R=pd.DataFrame(rows); pd.set_option('display.width',200); pd.set_option('display.max_rows',300)
print(R.round(3).to_string()); print('variants',len(R))
R.to_csv(SP+'r1.csv')
