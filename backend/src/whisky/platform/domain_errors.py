"""Stable business rejections crossing module use-case boundaries."""


class DomainRejection(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
