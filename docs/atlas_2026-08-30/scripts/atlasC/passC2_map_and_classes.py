import duckdb, numpy as np, pandas as pd, re, json
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
AT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas'
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
def q(s): r=con.execute(s).fetchall(); print(r); return r
S=2.2; BIN=10000
env=pd.read_parquet(f'{SC}/blockmap_env.parquet').sort_values('bin').reset_index(drop=True)
# intercept estimate per bin: midpoint of envelopes where both exist, else the one available
c=np.where(env.cu.notna()&env.cl.notna(), (env.cu+env.cl)/2, np.where(env.cu.notna(), env.cu, env.cl))
env['c']=c
# fill all bins between min and max with interpolation, then rolling median (±3 bins) to smooth
full=pd.DataFrame({'bin':np.arange(env.bin.min(), env.bin.max()+1)})
full=full.merge(env[['bin','c','nu','nl']], on='bin', how='left')
full['c']=full.c.interpolate(limit_direction='both')
full['c_s']=full.c.rolling(7, center=True, min_periods=1).median()
full['blk']=full.bin*BIN+BIN//2
full['t']=S*full.blk+full.c_s
# enforce monotonicity
full['t']=np.maximum.accumulate(full.t.values)
full[['bin','blk','t','c_s']].to_parquet(f'{SC}/blockmap.parquet')
con.execute(f"CREATE TABLE bm AS SELECT blk, t FROM '{SC}/blockmap.parquet' ORDER BY blk")
# validation vs Gamma resolved_at
con.execute(f"CREATE TABLE m AS SELECT * FROM '{AT}/struct_markets.parquet'")
con.execute(f"CREATE TABLE res AS SELECT condition_id, max(res_block) res_block FROM '{SC}/ctf_res.parquet' GROUP BY 1")
con.execute(f"CREATE TABLE prep AS SELECT condition_id, min(prep_block) prep_block FROM '{SC}/ctf_prep.parquet' GROUP BY 1")
con.execute("""CREATE MACRO blk2t(b) AS (SELECT b1.t + (b2.t-b1.t)*(b-b1.blk)/(b2.blk-b1.blk) FROM (SELECT * FROM bm WHERE blk<=b ORDER BY blk DESC LIMIT 1) b1, (SELECT * FROM bm WHERE blk>b ORDER BY blk LIMIT 1) b2)""")
# vectorised interpolation via asof joins
con.execute("""CREATE TABLE rv AS SELECT m.condition_id, m.resolved_at, m.last_ts, r.res_block, b1.blk b1blk, b1.t b1t, b2.blk b2blk, b2.t b2t,
   b1.t + (b2.t-b1.t)*(r.res_block-b1.blk)/(b2.blk-b1.blk) AS t_hat FROM m JOIN res r USING (condition_id)
   ASOF JOIN bm b1 ON r.res_block >= b1.blk ASOF JOIN bm b2 ON r.res_block < b2.blk""")
print('res-block time vs Gamma resolved_at (s), quantiles 1,5,25,50,75,95,99:')
q("SELECT count(*), quantile_cont(t_hat - resolved_at, [0.01,0.05,0.25,0.5,0.75,0.95,0.99]) FROM rv WHERE resolved_at IS NOT NULL")
print('res-block time minus last fill (s):')
q("SELECT count(*), quantile_cont(t_hat - last_ts, [0.001,0.01,0.05,0.25,0.5,0.75]) FROM rv")
con.execute("""CREATE TABLE pv AS SELECT m.condition_id, m.opens_at, m.first_ts, p.prep_block, b1.t + (b2.t-b1.t)*(p.prep_block-b1.blk)/(b2.blk-b1.blk) AS t_hat FROM m JOIN prep p USING (condition_id)
   ASOF JOIN bm b1 ON p.prep_block >= b1.blk ASOF JOIN bm b2 ON p.prep_block < b2.blk""")
print('prep-block time minus first fill (s) (should be <=0):')
q("SELECT count(*), quantile_cont(t_hat - first_ts, [0.5,0.9,0.95,0.99,0.999]) FROM pv")
print('prep-block time minus opens_at (s):')
q("SELECT count(*), quantile_cont(t_hat - opens_at, [0.05,0.25,0.5,0.75,0.95]) FROM pv")
# implied seconds per block by year
q("SELECT strftime(to_timestamp(t),'%Y') yr, (max(t)-min(t))/(max(blk)-min(blk)) spb FROM bm GROUP BY 1 ORDER BY 1")
# month boundaries in block space: for each month start epoch, find block by inverse interpolation
months=pd.date_range('2022-11-01','2026-06-01',freq='MS')
bmdf=con.execute("SELECT blk, t FROM bm ORDER BY blk").df()
mb=[]
for mth in months:
    e=mth.timestamp()
    b=np.interp(e, bmdf.t.values, bmdf.blk.values)
    mb.append((mth.strftime('%Y-%m'), int(round(b)), e))
mbdf=pd.DataFrame(mb, columns=['ym','start_block','start_epoch']); mbdf.to_parquet(f'{SC}/month_blocks.parquet'); print(mbdf.head(3), mbdf.tail(3))
# per-condition CTF resolution time estimate (for the sensitivity extension) 
con.execute(f"COPY (SELECT condition_id, res_block, t_hat AS res_t_hat, resolved_at, last_ts FROM rv) TO '{AT}/struct_ctf_resolution_time.parquet' (FORMAT PARQUET)")

# ---------- category classes ----------
CLASSES=['Sports','Politics','Crypto','Price Action','Finance','Culture','Sci-Tech','Other']
learn=con.execute("""SELECT category, arg_max(category_refined, usd) cls, sum(usd) usd FROM (SELECT category, category_refined, sum(usd) usd FROM m WHERE src='binary' GROUP BY 1,2) GROUP BY 1""").df()
learned={r.category:r.cls for r in learn.itertuples() if r.cls in CLASSES}
rules=[('Sports',r'\b(nba|nfl|mlb|nhl|ncaa|cbb|cfb|epl|la liga|serie a|bundesliga|ligue 1|ucl|champions league|europa|soccer|football|basketball|baseball|hockey|tennis|golf|ufc|mma|boxing|f1|formula|grand prix|nascar|cricket|rugby|olympic|world cup|premier league|mls|wnba|atp|wta|esports|lol|counter-strike|cs2|dota|valorant|super bowl|world series|stanley cup|nba finals|masters|open championship|wimbledon|us open|french open|australian open|copa|euro 20|afcon|liga mx|eredivisie|primeira|sports?|match|game)\b'),
 ('Crypto',r'\b(bitcoin|btc|ethereum|eth|solana|sol|xrp|doge|dogecoin|crypto|memecoin|airdrop|stablecoin|defi|nft|token|blockchain|binance|coinbase|altcoin|cardano|ada|ltc|litecoin|pepe|shib|bnb|hyperliquid|pump\.fun|ordinals|etf)\b'),
 ('Price Action',r'\b(price action|up or down|hits?\b.*\$|above|below|dip to|reach \$|\$[0-9])\b'),
 ('Politics',r'\b(election|elections|president|presidential|senate|house|congress|governor|mayor|primary|primaries|trump|biden|harris|vance|kamala|democrat|republican|gop|dnc|rnc|parliament|prime minister|pm\b|chancellor|cabinet|impeach|nominee|nomination|vote|referendum|ballot|legislat|politic|geopolit|ukraine|russia|israel|gaza|hamas|iran|china|taiwan|nato|ceasefire|war|military|sanction|tariff|immigration|border|supreme court|scotus|doge\b|executive order|shutdown|government|white house|pentagon|fbi|cia|doj|epstein|musk|elon|putin|zelensky|netanyahu|xi\b|modi|macron|starmer|merz|scholz|le pen|milei|lula|bolsonaro|poilievre|carney|trudeau|romania|germany|france|uk\b|canada|australia|japan|korea|india|brazil|argentina|mexico|poland|italy|spain|portugal|netherlands|ireland|sweden|norway|finland|czech|hungary|turkey|greece|venezuela|colombia|chile|peru|ecuador|bolivia|philippines|indonesia|thailand|pakistan|bangladesh|nigeria|kenya|south africa|egypt|saudi|uae|qatar|syria|lebanon|iraq|yemen|houthi|kurd|nyc|new york|california|texas|florida|virginia|jersey|mamdani|adams|cuomo|approval|polls?|fed chair|secretary|ambassador|minister|coalition|bundestag|knesset|duma|eu\b|european|brexit|un\b|united nations|who\b|g7|g20|brics|opec)\b'),
 ('Finance',r'\b(fed|fomc|rate cut|rate hike|interest rate|inflation|cpi|gdp|recession|unemployment|jobs report|nonfarm|treasur|bond|yield|stock|s&p|nasdaq|dow|nyse|ipo|earnings|tesla|apple|nvidia|microsoft|amazon|google|alphabet|meta|netflix|mstr|microstrategy|gme|gamestop|amc|oil|gold|silver|commodit|forex|dollar|euro|yen|yuan|bank|jpmorgan|goldman|debt ceiling|deficit|tax|tariff rate|economy|economic|macro|market cap|company|acquisition|merger|bankrupt|layoff|ceo)\b'),
 ('Culture',r'\b(oscar|oscars|academy award|grammy|emmy|golden globe|tony|bafta|cannes|box office|movie|film|album|song|billboard|spotify|music|concert|tour|taylor swift|kanye|ye\b|drake|beyonce|rihanna|kardashian|celebrity|celebrities|tv|television|netflix show|show|series|season|episode|game of thrones|stranger things|reality|bachelor|survivor|big brother|eurovision|miss universe|pageant|fashion|met gala|royal|king charles|prince|princess|harry|meghan|pope|papal|conclave|religion|church|time person|word of the year|tweet|tweets|mentions|say|says|mention|joe rogan|podcast|youtube|mrbeast|streamer|twitch|kick|tiktok|instagram|x\b|twitter|snl|late night|comedy|book|author|nobel|pulitzer|art|auction|lottery|powerball|gta|video game|nintendo|playstation|xbox|steam|awards?)\b'),
 ('Sci-Tech',r'\b(ai|artificial intelligence|openai|chatgpt|gpt|claude|anthropic|gemini|llm|deepseek|grok|xai|sora|agi|spacex|starship|nasa|rocket|launch|moon|mars|space|satellite|starlink|asteroid|comet|eclipse|weather|temperature|hurricane|tornado|earthquake|volcano|wildfire|flood|snow|rain|heat|climate|science|scientific|physics|chemistry|biology|vaccine|covid|pandemic|flu|measles|virus|disease|health|fda|cdc|drug|cancer|cure|nobel prize in|apple event|iphone|tesla robotaxi|robot|quantum|chip|semiconductor|intel|amd|tsmc|tech|technology|software|app|cyber|hack|breach|internet|meta ai|neuralink|autonomous|waymo|cybertruck|ufo|alien|uap)\b')]
def rule_class(tag):
    t=(tag or '').lower()
    for cls,rx in rules:
        if re.search(rx,t): return cls
    return None
tags=con.execute("SELECT category, sum(usd) usd, count(*) n FROM m GROUP BY 1").df()
rows=[]
for r in tags.itertuples():
    src='archive' if r.category in learned else None
    cls=learned.get(r.category)
    if cls is None:
        cls=rule_class(r.category); src='rule' if cls else 'unmapped'
    if cls is None: cls='Other'
    rows.append((r.category, cls, src, r.usd, r.n))
cm=pd.DataFrame(rows, columns=['category','cls','map_src','usd','n_markets'])
cm.to_parquet(f'{AT}/struct_category_classmap.parquet')
print(cm.groupby('map_src').agg(usd=('usd','sum'), n_tags=('category','count'), n_markets=('n_markets','sum')))
# markets table with class
con.execute(f"COPY (SELECT m.*, c.cls, c.map_src FROM m LEFT JOIN '{AT}/struct_category_classmap.parquet' c USING (category)) TO '{AT}/struct_markets.parquet' (FORMAT PARQUET)")
q(f"SELECT cls, count(*), sum(usd) FROM '{AT}/struct_markets.parquet' GROUP BY 1 ORDER BY 3 DESC")
q(f"SELECT src, map_src, count(*), sum(usd) FROM '{AT}/struct_markets.parquet' GROUP BY 1,2 ORDER BY 1,2")
# top unmapped/rule tags for negrisk for the report
print(cm[cm.map_src!='archive'].sort_values('usd',ascending=False).head(40).to_string())
