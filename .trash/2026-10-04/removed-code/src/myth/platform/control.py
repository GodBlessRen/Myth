    @property
    def aborted(self) -> bool:
        """旧调用方的只读 stopped 别名；停止只阻止未来派发。"""

        return self.stopped
