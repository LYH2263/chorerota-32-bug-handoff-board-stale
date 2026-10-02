class HandoverError(Exception):
    """交接链路业务校验失败；reason 为稳定的机器可读码，由 API 层映射为 4xx。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
