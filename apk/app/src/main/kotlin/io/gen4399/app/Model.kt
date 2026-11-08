package io.gen4399.app

/** 一条注册结果（由 C 侧回传，界面直接展示） */
data class SubmitResult(
    val kind: String,
    val ok: Boolean,
    val message: String,
    val username: String,
    val password: String,
    val path: String,
)

/** 身份信息 */
data class Identity(val name: String, val idcard: String, val qq: String = "")
