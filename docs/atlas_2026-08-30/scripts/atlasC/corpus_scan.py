import duckdb, glob, os, time
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
BASE='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/external/polymarket_v1'
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
ids=[l.strip() for l in open('/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/snapshots/20260829/corpus_condition_ids.txt') if l.strip()]
con.execute("CREATE TABLE ids AS SELECT unnest(?) AS condition_id", [ids])
# restrict scan to files from 2025-06 onward (corpus markets end 2025-12 .. 2026-05; first fills checked below)
files=[f for d in ['daily_aligned','daily_aligned_multi'] for f in sorted(glob.glob(f'{BASE}/{d}/*.parquet')) if os.path.basename(f)[:7]>='2025_06']
t=time.time()
con.execute(f"""COPY (SELECT f.condition_id, f.asset_id, f.block_timestamp ts, f.price, f.outcome_label, f.winning_outcome_label, epoch(f.resolved_at) resolved_at, epoch(f.close_at) close_at
   FROM read_parquet({files}) f WHERE f.condition_id IN (SELECT condition_id FROM ids)) TO '{SC}/corpus_fills.parquet' (FORMAT PARQUET)""")
print('scan', time.time()-t)
print(con.execute(f"SELECT count(*), count(distinct condition_id), min(ts), max(ts) FROM '{SC}/corpus_fills.parquet'").fetchall())
