package io.gen4399.app

/** 把结果渲染成 CSV / JSON / TXT。 */
object AccountExport {
    fun render(rows: List<SubmitResult>, format: String): String = when (format.lowercase()) {
        "json" -> json(rows)
        "txt" -> txt(rows)
        else -> csv(rows)
    }

    private fun csv(rows: List<SubmitResult>): String = buildString {
        appendLine("index,username,password,kind,ok,message,path")
        rows.forEachIndexed { index, row ->
            appendLine(
                listOf(
                    index + 1,
                    row.username,
                    row.password,
                    row.kind,
                    row.ok,
                    row.message.replace(",", "，").replace("\n", " "),
                    row.path,
                ).joinToString(",")
            )
        }
    }

    private fun json(rows: List<SubmitResult>): String = buildString {
        appendLine("[")
        rows.forEachIndexed { index, row ->
            append("  {")
            append("\"username\":").append(quote(row.username)).append(',')
            append("\"password\":").append(quote(row.password)).append(',')
            append("\"kind\":").append(quote(row.kind)).append(',')
            append("\"ok\":").append(row.ok).append(',')
            append("\"path\":").append(quote(row.path)).append(',')
            append("\"message\":").append(quote(row.message))
            append("}")
            if (index != rows.lastIndex) append(',')
            appendLine()
        }
        appendLine("]")
    }

    /** 账号|密码|结果 —— 便于再导回 sfz 风格的工具 */
    private fun txt(rows: List<SubmitResult>): String = buildString {
        rows.forEach { row ->
            appendLine("${row.username}|${row.password}|${row.kind}")
        }
    }

    private fun quote(value: String): String = buildString {
        append('"')
        for (ch in value) {
            when (ch) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> if (ch < ' ') append(String.format("\\u%04x", ch.code)) else append(ch)
            }
        }
        append('"')
    }
}
