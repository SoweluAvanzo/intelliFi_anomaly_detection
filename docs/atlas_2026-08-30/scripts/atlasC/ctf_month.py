import duckdb, sys, os, time, pandas as pd, numpy as np
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
BASE='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/external/polymarket_v1/CTF'
ev=sys.argv[1]; nchunk=int(sys.argv[2])
os.makedirs(f'{SC}/ctf_month',exist_ok=True)
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
COLL="('0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174','0x3A3BD7bb9528E159577F7C2e685CC81A765002E2','0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359')"
who="""CASE stakeholder WHEN '0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E' THEN 'exch' WHEN '0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296' THEN 'nradapter'
 WHEN '0xC5d563A36AE78145C45a50134d48A1215220f80a' THEN 'nrexch' WHEN '0xADa100874d00e3331D00F2007a9c336a65009718' THEN 'ada1' WHEN '0xAdA100Db00Ca00073811820692005400218FcE1f' THEN 'ada2' ELSE 'other' END""" if ev!='redemptions' else "'redeemer'"
# chunk boundaries from bins (equal event counts)
bins=pd.read_parquet(f'{SC}/ctf_{ev}_bins.parquet').groupby('bin').n.sum().sort_index()
cum=bins.cumsum()/bins.sum()
edges=[bins.index.min()*10000]+[int(bins.index[np.searchsorted(cum.values, k/nchunk)]*10000) for k in range(1,nchunk)]+[10**9]
con.execute(f"CREATE TABLE mb AS SELECT ym, start_block FROM '{SC}/month_blocks.parquet' ORDER BY start_block")
t=time.time()
for i in range(nchunk):
    outp=f'{SC}/ctf_month/{ev}_{i}.parquet'
    if os.path.exists(outp): continue
    lo,hi=edges[i],edges[i+1]
    con.execute(f"""COPY (WITH e AS (SELECT condition_id, cast(split_part(id,'_',2) as bigint) blk, {who} who, collateral_token, usdc_amount FROM '{BASE}/{ev}.parquet'
        WHERE collateral_token IN {COLL} AND cast(split_part(id,'_',2) as bigint) >= {lo} AND cast(split_part(id,'_',2) as bigint) < {hi})
      SELECT mb.ym, e.condition_id, e.who, e.collateral_token, count(*) n, sum(e.usdc_amount) usd FROM e ASOF JOIN mb ON e.blk >= mb.start_block GROUP BY 1,2,3,4) TO '{outp}.tmp' (FORMAT PARQUET)""")
    os.replace(f'{outp}.tmp', outp)
    print(ev, i, lo, hi, round(time.time()-t), flush=True)
print('DONE', ev)
