class PlanningError(Exception):
    def __init__(self, message, *, code="planning_error", status=422, details=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details
