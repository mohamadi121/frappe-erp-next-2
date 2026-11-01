"""Pure boundary for an in-process, verified full-office reset capability."""


def workflow_reset_allowed(*, actor, job, worker, receipt, scope, name, company):
    if worker is not True or not isinstance(receipt, dict) or not isinstance(scope, dict):
        return False
    return bool(actor and job and receipt.get('actor') == actor and receipt.get('job') == job
        and receipt.get('state') == 'running' and scope.get('actor') == actor and scope.get('job') == job
        and scope.get('digest') and scope['digest'] == receipt.get('digest')
        and company in scope.get('companies', ())
        and name in scope.get('targets', {}).get('ASOUD Workflow Definition', ()))


def completed_companies(details):
    if not isinstance(details, dict):
        return []
    groups = details.get('company_groups')
    if groups is not None:
        if not isinstance(groups, list) or any(not isinstance(group, list) for group in groups):
            return []
        companies = [name for group in groups for name in group]
    else:
        companies = details.get('companies', [])
    if (not isinstance(companies, list) or len(companies) > 2000
            or any(not isinstance(name, str) or not name or len(name) > 140 for name in companies)):
        return []
    return list(dict.fromkeys(companies))
