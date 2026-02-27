from __future__ import annotations


def _normalize_product_ids(dp_id):
    if dp_id is None:
        return []
    if isinstance(dp_id, str):
        values = [v.strip() for v in dp_id.split(",")]
    else:
        try:
            values = list(dp_id)
        except TypeError:
            values = [dp_id]

    out = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, bytes):
            value = value.decode(errors="ignore")
        clean = str(value).strip()
        if clean and clean not in out:
            out.append(clean)
    return out


def _quote_sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def _adql_sanitize_op_val(op_val):
    supported_operators = [
        "<=", ">=", "!=", "=", ">", "<",
        "not like ", "not in ", "not between ",
        "like ", "between ", "in ",
    ]
    if not isinstance(op_val, str):
        return f"= {op_val}"

    op_val = op_val.strip()
    for operator in supported_operators:
        if op_val.lower().startswith(operator):
            value = op_val[len(operator):].strip()
            return f"{operator} {value}"

    return f"= {_quote_sql_string(op_val)}"


def _build_ancillary_query(dp_ids, columns=None, column_filters=None, top=None,
                           count_only=False, order_by="", order_by_desc=True):
    table_name = "phase3v2.product_files"
    filters = dict(column_filters) if column_filters else {}

    where_parts = []
    if dp_ids:
        quoted_ids = ", ".join(_quote_sql_string(v) for v in dp_ids)
        where_parts.append(f"product_id in ({quoted_ids})")
    where_parts.extend([f"{k} {_adql_sanitize_op_val(v)}" for k, v in filters.items()])

    if isinstance(columns, str):
        selected_columns = [v.strip() for v in columns.split(",") if v.strip()]
    elif columns:
        selected_columns = list(columns)
    else:
        selected_columns = ["*"]

    if count_only:
        selected_columns = ["count(*)"]

    query = f"select {', '.join(selected_columns)} from {table_name}"
    if where_parts:
        query += " where " + " and ".join(where_parts)
    if order_by and not count_only:
        query += f" order by {order_by} {'desc' if order_by_desc else 'asc'}"
    if top is not None:
        query = query.replace("select ", f"select top {top} ", 1)
    return query


def _query_ancillary_fallback(self, dp_id=None, *, help=False, columns=None,
                              column_filters=None, ROW_LIMIT=None, **kwargs):
    table_name = "phase3v2.product_files"
    if help:
        self.list_column(table_name)
        return None

    dp_ids = _normalize_product_ids(dp_id)
    if not dp_ids:
        raise ValueError("dp_id must be specified when help=False.")

    if "maxrec" in kwargs:
        if ROW_LIMIT is not None:
            raise TypeError("Use either ROW_LIMIT or maxrec, not both.")
        ROW_LIMIT = kwargs.pop("maxrec")

    allowed_kwargs = {
        "top", "count_only", "get_query_payload", "authenticated",
        "order_by", "order_by_desc",
    }
    unknown_kwargs = set(kwargs) - allowed_kwargs
    if unknown_kwargs:
        unknown_str = ", ".join(sorted(unknown_kwargs))
        raise TypeError(f"Unexpected keyword argument(s): {unknown_str}")

    count_only = kwargs.get("count_only", False)
    query = _build_ancillary_query(
        dp_ids=dp_ids,
        columns=columns,
        column_filters=column_filters,
        top=kwargs.get("top"),
        count_only=count_only,
        order_by=kwargs.get("order_by", ""),
        order_by_desc=kwargs.get("order_by_desc", True),
    )

    if kwargs.get("get_query_payload", False):
        return query

    previous_ROW_LIMIT = None
    if ROW_LIMIT is not None:
        previous_ROW_LIMIT = self.ROW_LIMIT
        self.ROW_LIMIT = ROW_LIMIT

    try:
        result = self.query_tap(query=query, authenticated=kwargs.get("authenticated", False))
        if count_only:
            return int(list(result[0].values())[0]) if len(result) else 0
        return result
    finally:
        if previous_ROW_LIMIT is not None:
            self.ROW_LIMIT = previous_ROW_LIMIT


def prepare_eso(eso_export, ROW_LIMIT=None, **kwargs):
    """
    Return an Eso instance and ensure query_ancillary exists for older astroquery versions.
    """
    if "row_limit" in kwargs:
        if ROW_LIMIT is not None:
            raise TypeError("Use either ROW_LIMIT or row_limit, not both.")
        ROW_LIMIT = kwargs.pop("row_limit")
    if kwargs:
        unknown_str = ", ".join(sorted(kwargs))
        raise TypeError(f"Unexpected keyword argument(s): {unknown_str}")

    eso_class = eso_export if isinstance(eso_export, type) else type(eso_export)
    if not hasattr(eso_class, "query_ancillary"):
        eso_class.query_ancillary = _query_ancillary_fallback

    eso_instance = eso_export() if isinstance(eso_export, type) else eso_export
    if ROW_LIMIT is not None:
        eso_instance.ROW_LIMIT = ROW_LIMIT
    return eso_instance
