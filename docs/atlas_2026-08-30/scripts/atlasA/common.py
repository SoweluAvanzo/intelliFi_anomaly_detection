import duckdb, os
ROOT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection'
EXT=f'{ROOT}/data/external/polymarket_v1'
ATLAS=f'{ROOT}/data/parquet/atlas'
SCR='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA'
os.makedirs(ATLAS, exist_ok=True)
def connect(mem='4GB'):
    con=duckdb.connect()
    con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SCR}/duck_tmp'")
    con.execute("SET TimeZone='UTC'"); con.execute("SET enable_progress_bar=false")
    con.execute("SET preserve_insertion_order=false")
    return con
import glob, datetime as dt
def day_files(d0, d1):
    """list of (date, [files]) for days in [d0,d1] inclusive that exist in either dir"""
    out=[]
    d=d0
    while d<=d1:
        tag=d.strftime('%Y_%m_%d'); fs=[]
        for sub in ('daily_aligned','daily_aligned_multi'):
            p=f'{EXT}/{sub}/{tag}.parquet'
            if os.path.exists(p): fs.append(p)
        if fs: out.append((d,fs))
        d+=dt.timedelta(days=1)
    return out
def union_sql(files):
    # daily_aligned lacks neg_risk_market_id; union by name with NULL fill
    parts=[]
    for f in files:
        if 'daily_aligned_multi' in f:
            parts.append(f"SELECT *, 'multi' AS src FROM read_parquet('{f}')")
        else:
            parts.append(f"SELECT *, NULL::VARCHAR AS neg_risk_market_id, 'binary' AS src FROM read_parquet('{f}')")
    return " UNION ALL BY NAME ".join(parts)
# USDC value of fee: archive stores taker-SELL rows' fee in share units (BUY-side contract formula); convert with price
FEE_VAL="CASE WHEN taker_direction='SELL' THEN fee_usdc*price ELSE fee_usdc END"
