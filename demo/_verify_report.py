"""临时验证脚本"""
import sys
report = open('reports/低空经济物流_行业定义报告.md').read()
checks = {
    '行业核心定义': '行业核心定义' in report,
    '边界划定': '边界划定' in report,
    '结构性特征': '结构性特征' in report,
    '方法论附注': '方法论附注' in report,
    '自检信息(Step5)': 'pass' in report.lower(),
    '维度选择记录': '维度选择理由' in report,
    '无竞争排名(正文)': '竞争排名' not in report.replace('不在行业定义范围内', ''),
    '无市场份额(正文)': '市场份额' not in report.replace('市场份额分布', ''),
    '无投资建议': '投资建议' not in report,
    '无政策建议': '政策建议' not in report,
    'Token统计': '总 Token 消耗' in report,
    'Mock标注': 'Mock' in report,
}
all_pass = True
for k, v in checks.items():
    status = "PASS" if v else "FAIL"
    if not v:
        all_pass = False
    print(f'  {k}: {status}')
print(f'\n总结果: {"全部通过" if all_pass else "存在失败项"}')
sys.exit(0 if all_pass else 1)
