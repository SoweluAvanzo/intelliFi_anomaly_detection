import os, sys, time
os.environ.setdefault("INTELLIFI_SOURCE","archive")
os.environ.setdefault("INTELLIFI_DATA_DIR","/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data_stage2_v1")
os.environ.setdefault("INTELLIFI_ARCHIVE_CIDS","/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/snapshots/20260829_stage2_v1/corpus_condition_ids.txt")
os.environ.setdefault("INTELLIFI_ARCHIVE_START","2025-01-01")
sys.path.insert(0,"/home/sowelo/Scrivania/IntelliFi_anomaly_detection/src")
import duckdb
from intellifi.warehouse import open_warehouse
from intellifi.skill import position_skill, PositionSkillConfig
t=time.time()
con = open_warehouse()
con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4")
con.execute("PRAGMA temp_directory='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/duck_tmp'")
ps = position_skill(con, cfg=PositionSkillConfig())
out="/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/sampleA_position_skill.parquet"
ps.write_parquet(out)
print("rows", ps.shape, "cols", ps.columns, "elapsed", round(time.time()-t), flush=True)
