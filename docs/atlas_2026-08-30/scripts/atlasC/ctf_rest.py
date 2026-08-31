import duckdb, time
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
BASE='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/external/polymarket_v1/CTF'
con=duckdb.connect()
con.execute(f"SET enable_progress_bar=false; PRAGMA threads=3; SET memory_limit='3GB'; SET temp_directory='{SC}/ducktmp_ctf';")
COLL="('0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174','0x3A3BD7bb9528E159577F7C2e685CC81A765002E2','0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359')"
cls="""CASE stakeholder WHEN '0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E' THEN 'exch' WHEN '0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296' THEN 'nradapter'
 WHEN '0xC5d563A36AE78145C45a50134d48A1215220f80a' THEN 'nrexch' WHEN '0xADa100874d00e3331D00F2007a9c336a65009718' THEN 'ada1' WHEN '0xAdA100Db00Ca00073811820692005400218FcE1f' THEN 'ada2' ELSE 'other' END"""
t=time.time()
pass
pass
print('prep/res', time.time()-t, flush=True)
print('redemptions', time.time()-t, flush=True)
for ev in ['splits','merges']:
    con.execute(f"""COPY (SELECT cast(split_part(id,'_',2) as bigint)//10000 bin, {cls} AS who, collateral_token, count(*) n, sum(usdc_amount) usd
        FROM '{BASE}/{ev}.parquet' WHERE collateral_token IN {COLL} GROUP BY 1,2,3) TO '{SC}/ctf_{ev}_bins.parquet' (FORMAT PARQUET)""")
    print(ev,'bins', time.time()-t, flush=True)
con.execute(f"""COPY (SELECT cast(split_part(id,'_',2) as bigint)//10000 bin, collateral_token, count(*) n, sum(usdc_amount) usd
        FROM '{BASE}/redemptions.parquet' WHERE collateral_token IN {COLL} GROUP BY 1,2) TO '{SC}/ctf_redemptions_bins.parquet' (FORMAT PARQUET)""")
print('done', time.time()-t, flush=True)
