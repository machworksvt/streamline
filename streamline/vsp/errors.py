# streamline/vsp/errors.py
class VSPError(RuntimeError):
    pass

class VSPMissingResults(VSPError):
    def __init__(self, results_name: str):
        super().__init__(f"OpenVSP results not found: {results_name}")
