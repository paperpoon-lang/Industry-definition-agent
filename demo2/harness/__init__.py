# demo2/harness — v5.2 基础设施加固组件包
#
# v5.2 组件：
# - session_log.SessionEventLog: JSONL 持久化日志 + trace_id（注入式）
# - checkpoint.CheckpointManager: 多版本 Checkpoint + 过期清理
# - circuit_breaker.call_with_timeout: 带超时的重试封装（429 限流区分处理）
# - token_audit.TokenAudit: Token 持久化审计报表（v5 新增）
# - output_safety.OutputSafety: UTC 时间戳 + 版本号（v5 新增）
