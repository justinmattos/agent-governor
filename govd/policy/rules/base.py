class Rule:
    name = "rule"

    def applies(self, event):
        return False

    def evaluate(self, event, ctx):
        return None
