#!/usr/bin/env python3
"""Archive checks and reproducible Chinese report for Actions run 38651945004."""
import csv
import hashlib
import json
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MODES = ("jtty", "ft4", "ft8")
GROUPS = ("spread", "drift-low", "drift-high")
RATE = (0, .25, .5, .75, 1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 15, 18, 20)
RUN = 38651945004
SRC = "c25673947dd43529afbfab89e69fe2dda85fc744"
LAUNCH = "70966e578f24a58577bb3f10b05c9112e19b6990"

def read_csv(p):
    with p.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))

def key(row):
    return (row["mode"].lower(), row["group"], row["condition"])

def main():
    expected = {(m,"spread",c) for m in MODES for c in ("AWGN","MQ","MM","MD","HM","HD")}
    expected.update((m,"drift-low" if r<=3 else "drift-high",f"RATE_{r:05.2f}") for m in MODES for r in RATE)
    thresholds = read_csv(DATA/"thresholds.csv")
    points = read_csv(DATA/"points.csv")
    trials = read_csv(DATA/"trials.csv")
    assert len(expected)==75 and len(thresholds)==75 and {key(r) for r in thresholds} == expected
    assert len(points)==1267 and len(trials)==81872
    status = Counter(r["status"] for r in thresholds)
    assert status["estimated"]==50 and status["no_P50_error_floor"]==25
    measured_t, measured_p = [], []
    for m in MODES:
        for g in GROUPS:
            p = DATA/"measured"/(m+"-"+g)
            for name in ("trials.csv","points.csv","results.json","run.log"):
                assert (p/name).is_file(), p/name
            measured_t += read_csv(p/"trials.csv")
            measured_p += read_csv(p/"points.csv")
            json.loads((p/"results.json").read_text(encoding="utf-8"))
    fingerprint = lambda data: Counter(tuple(sorted(r.items())) for r in data)
    assert fingerprint(trials)==fingerprint(measured_t)
    assert fingerprint(points)==fingerprint(measured_p)
    counts=defaultdict(lambda:[0,0])
    seeds={}
    messages=defaultdict(set)
    for t in trials:
        k=key(t)+(t["snr_2500_db"],)
        counts[k][0]+=1
        assert t["decoded"] in ("0","1")
        counts[k][1]+=int(t["decoded"])
        seed_key=key(t)+(t["trial_index"],)
        if seed_key in seeds: assert seeds[seed_key]==t["seed"]
        seeds[seed_key]=t["seed"]
        messages[key(t)].add(t["message"])
    assert len(counts)==len(points)
    for p in points:
        n,s=counts[key(p)+(p["snr_2500_db"],)]
        assert n==int(p["trials"]) and s==int(p["successes"])
        assert abs(float(p["probability"])-s/n)<0.000002
    assert all(len(messages[k])==3 for k in expected)
    audit = dict(source_run_id=RUN, source_code_commit=SRC, launcher_commit=LAUNCH,
                 conditions=75, per_trial_records=len(trials), snr_points=len(points),
                 estimated_snr50=50, censored_error_floor=25, measured_groups=9,
                 measured_matches_merged=True, three_callsign_messages=True, seed_regression=True)
    (ROOT/"audit.json").write_text(json.dumps(audit,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    by = {key(r):r for r in thresholds}
    def threshold(r):
        return f'{float(r["p50_snr_2500_db"]):.2f}' if r["status"]=="estimated" else "未解析"
    lines = [
        "# WSJT-X JTTY / FT4 / FT8：精细信道鲁棒性测试（75 条件）", "",
        "## 来源与验收", "",
        "本报告仅采用 2026-10-14 至 15 日完成的实际测试数据，未使用上一轮测量替代。",
        f"- GitHub Actions 运行： https://github.com/Iu-yang1/wsjtx/actions/runs/{RUN}",
        f"- 固定实验代码 commit： {SRC}（bench/refined-channel-robustness）",
        f"- 启动提交： {LAUNCH}",
        "- 已验证 75/75 条件、81,872 条 per-trial 记录、1,267 个 SNR 点；50 个 SNR50 可估计，其余 25 个标记为错误平台或未交叉。",
        "- 九组 measured 原始 trials/points 与汇总文件逐条一致；每个条件有三种合法呼号消息，跨 SNR 共同随机数种子一致。", "",
        "## Watterson / AWGN 50% 解码门限", "",
        "|信道|JTTY|FT4|FT8|", "|---|---:|---:|---:|",
    ]
    for c in ("AWGN","MQ","MM","MD","HM","HD"):
        lines.append("|"+c+"|"+"|".join(threshold(by[(m,"spread",c)]) for m in MODES)+"|")
    lines += ["",
        "数值为 SNR2500（dB），越负代表在本实验配置下更弱信号即可达到 50% 的精确消息解码成功率。未解析不是零值，也不能外推其门限。",
        "AWGN：JTTY −15.90 dB，FT4 −18.29 dB，FT8 −21.67 dB；HD（30 Hz/7 ms）下 JTTY 为 −7.66 dB，FT4/FT8 在 +20 dB 端点均未成功解码。", "",
        "![QEX Figure 7 风格三模式解码概率](figures/figure1_qex_probability.png)", "",
        "![Watterson 门限对比](figures/figure2_itu_thresholds.png)", "",
        "## 未补偿多普勒率", "",
        "测试为发射波形加 0–20 Hz/s 线性 chirp 后叠加 AWGN，不含 Watterson 复合衰落及接收端动态补偿。可估计 SNR50 的最大测试变化率：JTTY 15 Hz/s、FT4 5 Hz/s、FT8 1 Hz/s。",
        "![多普勒率对比](figures/figure3_doppler_rate.png)", "",
        "## 统计与高 SNR 错误平台", "",
        "FT8 的 HM（10 Hz/3 ms）虽然拟合 SNR50 为 −5.93 dB，但 +20 dB 的解码成功率为 85/128（66.4%）。高 SNR 平台不能用单一 SNR50 完整描述。",
        "使用固定 -30 至 +20 dB 的 5 dB 粗网格（16 trials/点）及 0.5 dB 密集网格（128 trials/点）。点概率的 Wilson 95% 区间不等同于门限的不确定性；门限区间基于 Jeffreys-Beta 抽样与加权单调回归，不能覆盖系统建模误差。同一 trial_index 的 seed 在不同 SNR 点复用，跨 SNR 样本不独立。", "",
        "## 对照 QEX 2020", "",
        "Franke / Somerville / Taylor, The FT4 and FT8 Communication Protocols, QEX 2020：https://wsjt.sourceforge.io/FT4_FT8_QEX.pdf 。本轮与论文的解码器版本、信道统计和消息集合并不完全一致，不应把门限差异直接解释为算法改进。",
        "|信道|本轮FT4|QEX FT4|本轮FT8|QEX FT8|", "|---|---:|---:|---:|---:|",
        "|AWGN|−18.29|−17.5|−21.67|−20.8|",
        "|MD|−16.00|−15.2|−19.81|−18.6|",
        "|HM|−11.19|−12.2|−5.93|−8.6|", "",
        "## 完整 75 条件汇总", "",
        "|模式|分组|条件|SNR50/dB|状态|高端 SNR 正确率|",
        "|---|---|---|---:|---|---:|"]
    for r in sorted(thresholds,key=lambda r:(r["mode"],r["group"],r["condition"])):
        lines.append("|"+"|".join([r["mode"].upper(),r["group"],r["condition"],threshold(r),
                  r["status"],f'{float(r["end_success_probability"]):.4f}'])+"|")
    lines += ["", "## 数据文件与限制", "",
       "- data/trials.csv：81,872 次模拟的消息、种子和解码结果；data/points.csv：1,267 个概率点；data/thresholds.csv：门限及其区间。",
       "- data/measured/：九组 Actions measured 产物的原始 CSV、results.json 和日志；figures/：Actions 生成的 PNG/SVG 图；audit.json：归档核验；SHA256SUMS.txt：文件哈希。",
       "- 实验协议：https://github.com/Iu-yang1/wsjtx/blob/"+SRC+"/tools/channel-bench/REFINED_QEX_PROTOCOL.md", "",
       "不同模式的时长、载荷、同步及解码设置不同；这些是仿真下特定消息集合的相对性能结果，而不是 OTA 实机测试或等比特吞吐量性能对照。"]
    (ROOT/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    (ROOT/"README.md").write_text(
        "# Refined QEX 75-condition result archive\n\n"
        "[中文报告](report.md) · [中文 PDF](report.pdf) · "
        "[QEX 解码概率](figures/figure1_qex_probability.png) · "
        "[Watterson](figures/figure2_itu_thresholds.png) · "
        "[Doppler](figures/figure3_doppler_rate.png)\n\n"
        "Source Actions run: https://github.com/Iu-yang1/wsjtx/actions/runs/"+str(RUN)+"\n\n"
        "Experiment source commit: "+SRC+"; launcher commit: "+LAUNCH+".\n\n"
        "75/75 conditions, 81,872 trials, 1,267 points, 50 estimable SNR50 values. "
        "Includes all nine measured original data groups, merged per-trial files, "
        "plots and integrity checks. No previous-round data used.\n",encoding="utf-8")
    entries=[]
    for file in sorted(ROOT.rglob("*")):
        if file.is_file() and file.name != "SHA256SUMS.txt" and file.name != "report.pdf":
            entries.append(hashlib.sha256(file.read_bytes()).hexdigest()+"  "+str(file.relative_to(ROOT)))
    (ROOT/"SHA256SUMS.txt").write_text("\n".join(entries)+"\n",encoding="utf-8")
    print(json.dumps(audit,ensure_ascii=False))

if __name__=="__main__":
    main()
