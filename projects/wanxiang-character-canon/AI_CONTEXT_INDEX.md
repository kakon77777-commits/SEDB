# Wanxiang AI context discovery pointer

Purpose: direct compacted contexts and other AIs to the single canonical Wanxiang research index.

- Canonical human index: `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\AI_CONTEXT_INDEX.md`
- Machine index: `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\analysis\sedb-wave2-4\context-index.json`

Refresh command:

```powershell
cd 'D:\Ai\work together\SEDB'
$env:PYTHONPATH = 'current\src;projects\wanxiang-character-canon'
python 'D:\Ai\work together\SEDB\projects\wanxiang-character-canon\context_index.py' refresh
python projects\wanxiang-character-canon\cli.py context-index
```

Evidence boundary: this pointer deliberately contains no changing counts, fingerprints, or report summaries. Read and validate the canonical and machine indexes instead.
