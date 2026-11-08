package io.gen4399.app

import android.graphics.BitmapFactory
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 一次最多载入多少条身份（防止 25MB 文件把内存打爆） */
private const val MAX_IDENTITIES = 2000

/** 文本框最多容纳多少字符（粘贴超长文本时截断） */
private const val MAX_TEXT_CHARS = 200_000

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { App() } }
    }
}

/** 设置 */
data class Settings(
    val count: Int = 1,
    val prefix: String = "",
    val suffix: String = "",
    val channel: String = "unified",
    val intervalSec: Int = 20,
    val dryRun: Boolean = true,
    val randomize: Boolean = true,
    val passwordLength: Int = 16,
)

/** 待输入的验证码 */
data class PendingCaptcha(val image: ByteArray, val deferred: CompletableDeferred<String?>)

/** 大文件导入的统计（避免把 25MB 文本塞进 TextField 导致闪退） */
data class ImportStats(
    val lines: Int = 0,
    val valid: Int = 0,
    val kept: Int = 0,
    val encoding: String = "",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var tab by remember { mutableStateOf(0) }
    var sfzText by remember { mutableStateOf("") }
    val identities = remember { mutableStateListOf<Identity>() }
    val results = remember { mutableStateListOf<SubmitResult>() }
    var settings by remember { mutableStateOf(Settings()) }
    var running by remember { mutableStateOf(false) }
    var progress by remember { mutableStateOf(0f) }
    var statusLine by remember { mutableStateOf("就绪") }
    var logText by remember { mutableStateOf("") }
    var pendingCaptcha by remember { mutableStateOf<PendingCaptcha?>(null) }
    var importStats by remember { mutableStateOf(ImportStats()) }
    var fileUri by remember { mutableStateOf<String?>(null) }
    var nextOffset by remember { mutableStateOf(0L) }
    var atEof by remember { mutableStateOf(true) }
    var pageIndex by remember { mutableStateOf(0) }
    val prefs = remember { context.getSharedPreferences("gen4399", android.content.Context.MODE_PRIVATE) }

    fun appendLog(line: String) {
        logText = (logText + line + "\n").takeLast(4000)
    }

    fun parseSfz(text: String) {
        identities.clear()
        var lines = 0
        var valid = 0
        for (raw in text.lineSequence()) {
            lines++
            val line = raw.trim()
            if (line.isEmpty() || line.startsWith("#")) continue
            val parts = line.split('|', ',').map { it.trim() }
            if (parts.size < 2 || parts[0].isEmpty() || parts[1].isEmpty()) continue
            valid++
            if (identities.size < MAX_IDENTITIES) {
                identities += Identity(parts[0], parts[1], parts.getOrElse(2) { "" })
            }
        }
        importStats = ImportStats(lines = lines, valid = valid, kept = identities.size)
        statusLine = "已解析 ${identities.size} 条身份" +
            if (valid > identities.size) "（超上限，只保留前 $MAX_IDENTITIES 条）" else ""
        appendLog(statusLine)
    }

    fun applyPage(page: SfzFile.Page, source: String, firstPage: Boolean) {
        identities.clear()
        identities.addAll(page.identities)
        importStats = page.stats
        nextOffset = page.nextOffset
        atEof = page.eof
        if (firstPage) {
            pageIndex = 1
            sfzText = page.preview
            results.clear()   // 新文件才清空结果，续跑会累积
        } else {
            pageIndex++
        }
        prefs.edit()
            .putString("sfz_uri", source)
            .putLong("sfz_offset", page.nextOffset)
            .putInt("sfz_page", pageIndex)
            .apply()
        statusLine = buildString {
            append("第 $pageIndex 批：${page.identities.size} 条")
            if (page.stats.encoding.isNotEmpty()) append("，编码 ${page.stats.encoding}")
            append(if (page.eof) "（已到文件末尾）" else "（还有后续）")
        }
        appendLog(statusLine)
    }

    fun loadPage(uriString: String, offset: Long, firstPage: Boolean) {
        statusLine = "正在读取文件…"
        scope.launch {
            val page = withContext(Dispatchers.IO) {
                runCatching {
                    SfzFile.loadPage(context, android.net.Uri.parse(uriString), offset, MAX_IDENTITIES)
                }.getOrNull()
            }
            if (page == null) {
                statusLine = "读取文件失败"
                return@launch
            }
            fileUri = uriString
            applyPage(page, uriString, firstPage)
        }
    }

    val importLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        loadPage(uri.toString(), 0L, firstPage = true)
    }

    var exportFormat by remember { mutableStateOf("csv") }

    val exportLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/plain")) { uri ->
        if (uri != null) {
            val content = AccountExport.render(results, exportFormat)
            val okCount = AccountExport.successes(results).size
            val ok = runCatching {
                context.contentResolver.openOutputStream(uri)?.use { it.write(content.toByteArray()) }
            }.isSuccess
            statusLine = if (ok) {
                "已导出 $okCount 条成功账号（${exportFormat.uppercase()}，失败/未知的未导出）"
            } else {
                "导出失败"
            }
            appendLog(statusLine)
        }
    }

    fun startRun() {
        if (running) return
        if (identities.isEmpty()) {
            statusLine = "先解析身份（或导入 sfz.txt）"
            return
        }
        running = true
        progress = 0f
        val startIndex = results.size
        val planned = minOf(settings.count, identities.size)
        val sfz = identities.joinToString("\n") { "${it.name}|${it.idcard}|${it.qq}" }
        appendLog("开始：${minOf(settings.count, identities.size)} 个账号，通道 ${settings.channel}，dry-run=${settings.dryRun}")

        // 真正的编排在 C（libgen4399.so）里跑，这里只做回调展示
        val callback = object : Native.Callback {
            override fun transport(
                url: String,
                method: String,
                contentType: String,
                body: String,
                cookieHeader: String,
                referer: String,
            ): Array<String> = HttpTransport.send(url, method, contentType, body, cookieHeader, referer)

            override fun fetchBinary(url: String, cookieHeader: String, referer: String): Array<Any> =
                HttpTransport.fetchBytes(url, cookieHeader, referer)

            override fun onProgress(
                index: Int,
                total: Int,
                username: String,
                password: String,
                kind: String,
                ok: Boolean,
                message: String,
            ) {
                scope.launch {
                    results += SubmitResult(kind, ok, message, username, password, settings.channel)
                    progress = index.toFloat() / total.coerceAtLeast(1)
                    statusLine = "$index/$total：$kind"
                    appendLog("[$index] $username $kind ${message.take(60)}")
                }
            }

            override fun askCaptcha(image: ByteArray): String? {
                // 先试自动识别（unified 60×30），认不出再弹窗
                CaptchaAuto.solve(image)?.let { code ->
                    scope.launch { appendLog("验证码自动识别：$code") }
                    return code
                }
                val deferred = CompletableDeferred<String?>()
                scope.launch { pendingCaptcha = PendingCaptcha(image, deferred) }
                val code = kotlinx.coroutines.runBlocking { deferred.await() }
                scope.launch { pendingCaptcha = null }
                return code
            }
        }

        scope.launch {
            val success = withContext(Dispatchers.IO) {
                runCatching {
                    Native.runBatch(
                        identities = sfz,
                        path = settings.channel,
                        count = settings.count,
                        prefix = settings.prefix,
                        suffix = settings.suffix,
                        intervalSec = if (settings.dryRun) 0 else settings.intervalSec,
                        dryRun = settings.dryRun,
                        sendRealname = true,
                        randomize = settings.randomize,
                        callback = callback,
                    )
                }.getOrElse { -1 }
            }
            running = false
            val batch = results.drop(startIndex)
            val dryRun = batch.count { it.kind == "dry_run" }
            val failed = batch.count { !it.ok && it.kind != "dry_run" }
            statusLine = if (success >= 0) {
                "本轮 $planned 个：成功 $success · dry-run $dryRun · 失败 $failed · 累计 ${results.size} 条"
            } else {
                "运行出错（native 返回 $success）"
            }
            appendLog(statusLine)
            if (success >= 0) prefs.edit().putLong("sfz_offset", nextOffset).apply()
        }
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("gen4399") }) },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            TabRow(selectedTabIndex = tab) {
                listOf("身份", "设置", "运行").forEachIndexed { index, title ->
                    Tab(selected = tab == index, onClick = { tab = index }, text = { Text(title) })
                }
            }
            when (tab) {
                0 -> IdentityTab(
                    text = sfzText,
                    onTextChange = { value ->
                        sfzText = if (value.length > MAX_TEXT_CHARS) {
                            statusLine = "文本过长，已截断到 $MAX_TEXT_CHARS 字符"
                            value.take(MAX_TEXT_CHARS)
                        } else {
                            value
                        }
                    },
                    identities = identities,
                    pageIndex = pageIndex,
                    atEof = atEof,
                    hint = if (importStats.lines > 0) {
                        "文件 ${importStats.lines} 行 · 有效 ${importStats.valid} 条 · 已载入 ${importStats.kept} 条"
                    } else "",
                    onParse = { parseSfz(sfzText) },
                    onImport = { importLauncher.launch(arrayOf("text/plain", "*/*")) },
                    canContinue = fileUri != null && !atEof,
                    onContinue = { fileUri?.let { loadPage(it, nextOffset, firstPage = false) } },
                )
                1 -> SettingsTab(settings = settings, onChange = { settings = it }, identityCount = identities.size)
                else -> RunTab(
                    running = running,
                    progress = progress,
                    status = statusLine,
                    log = logText,
                    results = results,
                    onStart = { startRun() },
                    onExport = { format ->
                        val okCount = results.count { it.ok }
                        if (okCount == 0) {
                            statusLine = "没有注册成功的账号可导出（共 ${results.size} 条，成功 0）"
                        } else {
                            exportFormat = format
                            exportLauncher.launch("gen4399-accounts.$format")
                        }
                    },
                )
            }
        }
    }

    pendingCaptcha?.let { pending ->
        CaptchaDialog(
            image = pending.image,
            onConfirm = { code -> pending.deferred.complete(code) },
            onDismiss = { pending.deferred.complete(null); pendingCaptcha = null },
        )
    }
}

@Composable
private fun IdentityTab(
    text: String,
    onTextChange: (String) -> Unit,
    identities: List<Identity>,
    pageIndex: Int,
    atEof: Boolean,
    hint: String,
    onParse: () -> Unit,
    onImport: () -> Unit,
    canContinue: Boolean,
    onContinue: () -> Unit,
) {
    Column(Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("每行格式：姓名|身份证[|QQ]", style = MaterialTheme.typography.bodySmall)
        if (hint.isNotEmpty()) {
            Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
        }
        Text(
            "大文件只载入前 $MAX_IDENTITIES 条，其余不占内存",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.outline,
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = text,
            onValueChange = onTextChange,
            modifier = Modifier.fillMaxWidth().height(180.dp),
            placeholder = { Text("张三|110105198803121893") },
        )
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onParse) { Text("解析") }
            OutlinedButton(onClick = onImport) { Text("导入 sfz.txt") }
            OutlinedButton(onClick = onContinue, enabled = canContinue) {
                Text(if (canContinue) "继续下一批" else "已到末尾")
            }
        }
        if (pageIndex > 0) {
            Text(
                "当前第 $pageIndex 批 · 断点续跑已开启（上面文本只是前 100 行预览，" +
                    "直接点「解析」会以预览内容为准）",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        Spacer(Modifier.height(12.dp))
        Text("共 ${identities.size} 条", style = MaterialTheme.typography.titleSmall)
        identities.take(50).forEachIndexed { index, identity ->
            val problems = Rules.validateIdcard(identity.idcard) + Rules.validateRealname(identity.name)
            Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                Column(Modifier.padding(10.dp)) {
                    Text("${index + 1}. ${identity.name}  ${Rules.maskIdcard(identity.idcard)}")
                    if (problems.isEmpty()) {
                        Text("校验通过", style = MaterialTheme.typography.bodySmall)
                    } else {
                        Text(problems.joinToString("；"), style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error)
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsTab(settings: Settings, onChange: (Settings) -> Unit, identityCount: Int) {
    Column(Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("通道", style = MaterialTheme.typography.titleSmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("unified", "web").forEach { channel ->
                FilterChip(
                    selected = settings.channel == channel,
                    onClick = { onChange(settings.copy(channel = channel)) },
                    label = { Text(channel) },
                )
            }
        }

        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = settings.count.toString(),
                onValueChange = { onChange(settings.copy(count = it.toIntOrNull() ?: 1)) },
                label = { Text("生成数量") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.width(140.dp),
            )
            OutlinedTextField(
                value = settings.passwordLength.toString(),
                onValueChange = { onChange(settings.copy(passwordLength = it.toIntOrNull() ?: 16)) },
                label = { Text("密码长度") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.width(140.dp),
            )
        }

        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = settings.prefix,
                onValueChange = { onChange(settings.copy(prefix = it.trim())) },
                label = { Text("用户名前缀") },
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = settings.suffix,
                onValueChange = { onChange(settings.copy(suffix = it.trim())) },
                label = { Text("用户名后缀") },
                modifier = Modifier.weight(1f),
            )
        }

        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = settings.intervalSec.toString(),
            onValueChange = { onChange(settings.copy(intervalSec = it.toIntOrNull() ?: 0)) },
            label = { Text("账号间隔（秒）") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.width(180.dp),
        )

        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = settings.dryRun, onCheckedChange = { onChange(settings.copy(dryRun = it)) })
            Spacer(Modifier.width(8.dp))
            Text("dry-run（只组装字段，不真正提交）")
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = settings.randomize, onCheckedChange = { onChange(settings.copy(randomize = it)) })
            Spacer(Modifier.width(8.dp))
            Text("随机挑选身份（避免总用前几条，已被用尽）")
        }

        Spacer(Modifier.height(12.dp))
        Text(
            "将生成 ${minOf(settings.count, identityCount)} 个账号；用户名示例：${
                runCatching { Rules.generateUsername(12, settings.prefix, settings.suffix) }.getOrDefault("-")
            }",
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun RunTab(
    running: Boolean,
    progress: Float,
    status: String,
    log: String,
    results: List<SubmitResult>,
    onStart: () -> Unit,
    onExport: (String) -> Unit,
) {
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        androidx.compose.foundation.layout.FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Button(onClick = onStart, enabled = !running) { Text(if (running) "运行中…" else "开始") }
            OutlinedButton(onClick = { onExport("csv") }) { Text("导出 CSV") }
            OutlinedButton(onClick = { onExport("json") }) { Text("导出 JSON") }
            OutlinedButton(onClick = { onExport("txt") }) { Text("导出 TXT") }
            if (running) CircularProgressIndicator(Modifier.width(24.dp).height(24.dp))
        }
        Spacer(Modifier.height(10.dp))
        LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(6.dp))
        Text(status, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(10.dp))
        HorizontalDivider()
        val okCount = results.count { it.ok }
        Text(
            "成功 $okCount / 共 ${results.size} 条（导出只包含成功记录）",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.primary,
        )
        LazyColumn(Modifier.weight(0.6f)) {
            items(results) { r ->
                Column(Modifier.padding(vertical = 4.dp)) {
                    Text(
                        "${r.username}  ${r.kind}",
                        color = when {
                            r.ok -> MaterialTheme.colorScheme.primary
                            r.kind == "dry_run" -> MaterialTheme.colorScheme.secondary
                            else -> MaterialTheme.colorScheme.error
                        },
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(r.message.take(90), style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        HorizontalDivider()
        Text(log, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
            modifier = Modifier.weight(0.4f).verticalScroll(rememberScrollState()))
    }
}

@Composable
private fun CaptchaDialog(image: ByteArray, onConfirm: (String) -> Unit, onDismiss: () -> Unit) {
    var code by remember { mutableStateOf("") }
    val bitmap = remember(image) { BitmapFactory.decodeByteArray(image, 0, image.size) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("输入验证码") },
        text = {
            Column {
                if (bitmap != null) {
                    Image(
                        bitmap = bitmap.asImageBitmap(),
                        contentDescription = "captcha",
                        modifier = Modifier.fillMaxWidth(),
                    )
                } else {
                    Text("图片解码失败")
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(value = code, onValueChange = { code = it.take(4) }, label = { Text("4 位字符") })
            }
        },
        confirmButton = { TextButton(onClick = { onConfirm(code.trim()) }) { Text("提交") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("跳过") } },
    )
}
