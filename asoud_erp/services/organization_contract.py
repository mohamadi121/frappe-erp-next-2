def validate_rows(rows):
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("Invalid organization rows (maximum 500)")
    positions, employees = {}, set()
    normalized = []
    for source in rows:
        row = {key: str(source.get(key) or "").strip()
               for key in ("code", "title", "parent", "department", "employee")}
        if not row["code"] or not row["title"] or row["code"] in positions:
            raise ValueError("Missing title/code or duplicate code")
        if row["employee"]:
            if row["employee"] in employees:
                raise ValueError("Employee is assigned to more than one position")
            employees.add(row["employee"])
        positions[row["code"]] = row
        normalized.append(row)
    for row in normalized:
        visited, parent = {row["code"]}, row["parent"]
        while parent:
            if parent not in positions:
                raise ValueError("Parent position does not exist")
            if parent in visited:
                raise ValueError("Organization cycle is not allowed")
            visited.add(parent)
            parent = positions[parent]["parent"]
    return normalized

