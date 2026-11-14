package io.gen4399.app

import android.os.Build

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
import androidx.compose.runtime.LaunchedEffect
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
    val proxies: String = "",
    val proxyStrategy: String = "round-robin",
    val keepAlive: Boolean = true,
    val apiUrl: String = "",
    val apiAuth: String = "",
    val apiNum: Int = 5,
    val freeProxyCount: Int = 25,
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
    var autoStartToken by remember { mutableStateOf(0) }
    var proxyStatus by remember { mutableStateOf("") }
    var publicIp by remember { mutableStateOf("") }
    var fileUri by remember { mutableStateOf<String?>(null) }
    var nextOffset by remember { mutableStateOf(0L) }
    var atEof by remember { mutableStateOf(true) }
    var pageIndex by remember { mutableStateOf(0) }
    val prefs = remember { context.getSharedPreferences("gen4399", android.content.Context.MODE_PRIVATE) }
    val bankPath = remember { java.io.File(context.filesDir, "web_captcha_bank.txt").absolutePath }

    fun appendLog(line: String) {
        logText = (logText + line + "\n").takeLast(4000)
    }

    LaunchedEffect(Unit) {
        val loaded = runCatching { Native.loadWebBank(bankPath) }.getOrDefault(0)
        if (loaded > 0) appendLog("已加载自学习字库 $loaded 条")
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
            if (page.identities.isNotEmpty()) autoStartToken += 1
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

    val notificationPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { }

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
        val proxyLines = settings.proxies.lines().filter { it.isNotBlank() }
        HttpTransport.configure(settings.proxies, settings.proxyStrategy)
        if (proxyLines.isNotEmpty()) {
            scope.launch {
                statusLine = "检测 ${proxyLines.size} 条代理可达性…"
                val outcomes = ProxyProbe.testAll(proxyLines)
                val alive = outcomes.filter { it.alive }.map { it.line }
                if (alive.isEmpty()) {
                    appendLog("代理全部不可达，本轮改走直连")
                    HttpTransport.configure("", settings.proxyStrategy)
                } else {
                    appendLog("代理可达 ${alive.size}/${proxyLines.size}")
                    HttpTransport.configure(alive.joinToString("\n"), settings.proxyStrategy)
                    settings = settings.copy(proxies = alive.joinToString("\n"))
                }
            }
        }
        if (settings.keepAlive) {
            KeepAliveService.start(context, "准备中…")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) !=
                android.content.pm.PackageManager.PERMISSION_GRANTED
            ) {
                runCatching { notificationPermission.launch(android.Manifest.permission.POST_NOTIFICATIONS) }
            }
        }
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

            override fun onCaptchaResult(code: String, passed: Boolean) {
                if (!passed) return
                val added = CaptchaAuto.learnIfConfirmed(code)
                if (added > 0) {
                    val saved = Native.saveWebBank(bankPath)
                    scope.launch { appendLog("自学习：$code 新增 $added 个字形（已存 $saved 条）") }
                }
            }

            override fun onAccountStart(index: Int) {
                HttpTransport.beginAccount()
                scope.launch { appendLog("[$index] 出口 ${HttpTransport.currentProxyLabel()}") }
            }

            override fun onProgress(
                index: Int,
                total: Int,
                username: String,
                password: String,
                kind: String,
                ok: Boolean,
                message: String,
            ) {
                if (settings.keepAlive) {
                    val success = results.count { it.ok }
                    KeepAliveService.update(context, "$index/$total · 成功 $success · $kind")
                }
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
            if (settings.keepAlive) KeepAliveService.stop(context)
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
            if (success >= 0 && !atEof) {
                appendLog("自动载入下一批…")
                fileUri?.let { loadPage(it, nextOffset, firstPage = false) }
            }
        }
    }

    LaunchedEffect(autoStartToken) {
        if (autoStartToken > 0) startRun()
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("gen4399") }) },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            TabRow(selectedTabIndex = tab) {
                listOf("设置", "运行").forEachIndexed { index, title ->
                    Tab(selected = tab == index, onClick = { tab = index }, text = { Text(title) })
                }
            }
            when (tab) {
                0 -> SettingsTab(
                    settings = settings,
                    status = statusLine,
                    proxyStatus = proxyStatus,
                    publicIp = publicIp,
                    onChange = { settings = it },
                    identityCount = identities.size,
                    pageIndex = pageIndex,
                    atEof = atEof,
                    importStats = importStats,
                    onImport = { importLauncher.launch(arrayOf("text/plain", "*/*")) },
                    onContinue = { fileUri?.let { loadPage(it, nextOffset, firstPage = false) } },
                    onPullFromApi = {
                        val url = settings.apiUrl.trim()
                        if (url.isEmpty()) {
                            proxyStatus = "先填提取链接"
                        } else {
                            scope.launch {
                                proxyStatus = "正在从 API 提取…"
                                val attempt = runCatching {
                                    ApiProxy.pull(url, settings.apiAuth.trim(), settings.apiNum)
                                }
                                val result = attempt.getOrNull()
                                if (result == null || result.lines.isEmpty()) {
                                    val reason = attempt.exceptionOrNull()?.let {
                                        "${it.javaClass.simpleName}: ${it.message}"
                                    } ?: "没解析到 IP（返回：${result?.snippet ?: ""}）"
                                    proxyStatus = if (reason.contains("401") || reason.contains("API_AUTH_DENY")) {
                                        "401 未授权：这个 key 要 IP 白名单。把出口 IP 加到青果后台，" +
                                            "或改用通道直连（直接粘 IP:端口，不用 API）"
                                    } else {
                                        "提取失败：$reason"
                                    }
                                    appendLog(proxyStatus)
                                } else {
                                    settings = settings.copy(proxies = result.lines.joinToString("\n"))
                                    proxyStatus = "已提取 ${result.lines.size} 条（原始 ${result.raw} 条）· ${result.requestUrl}"
                                    appendLog(proxyStatus)
                                }
                            }
                        }
                    },
                    onCheckIp = {
                        scope.launch {
                            proxyStatus = "正在查询出口 IP…"
                            val ip = NetInfo.currentIp()
                            publicIp = ip ?: ""
                            proxyStatus = if (ip != null) {
                                "当前出口 IP：$ip（白名单要加这个）"
                            } else {
                                "查不到出口 IP（网络受限）"
                            }
                        }
                    },
                    onTestProxies = {
                        val lines = settings.proxies.lines().filter { it.isNotBlank() }
                        if (lines.isEmpty()) {
                            proxyStatus = "代理池是空的：先「从 API 提取」，或手动粘贴，或点「获取免费代理」"
                        } else {
                            scope.launch {
                                proxyStatus = "正在检测 ${lines.size} 条代理的可达性…"
                                val outcomes = ProxyProbe.testAll(lines) { msg -> scope.launch { proxyStatus = msg } }
                                val alive = outcomes.filter { it.alive }
                                if (alive.isEmpty()) {
                                    proxyStatus = "0/${lines.size} 可达（全部超时）"
                                } else {
                                    settings = settings.copy(proxies = alive.map { it.line }.joinToString("\n"))
                                    val avg = alive.map { it.millis }.average().toInt()
                                    proxyStatus = "可达 ${alive.size}/${lines.size}，平均 ${avg}ms，已移除不可达的"
                                }
                                appendLog(proxyStatus)
                            }
                        }
                    },
                    onFetchFreeProxies = {
                        scope.launch {
                            proxyStatus = "正在获取免费代理…"
                            val result = runCatching {
                                FreeProxy.refresh(settings.freeProxyCount) { msg ->
                                    scope.launch { proxyStatus = msg }
                                }
                            }.getOrNull()
                            if (result == null || result.alive.isEmpty()) {
                                proxyStatus = "没取到可用代理（免费代理存活率低，或当前网络拿不到列表）"
                                appendLog(proxyStatus)
                            } else {
                                settings = settings.copy(proxies = result.alive.joinToString("\n"))
                                proxyStatus = "免费代理：${result.alive.size}/${result.fetched} 个可用，已填入"
                                appendLog(proxyStatus)
                            }
                        }
                    },
                    onRequestBatteryExemption = {
                        runCatching {
                            val intent = android.content.Intent(
                                android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                                android.net.Uri.parse("package:${context.packageName}"),
                            )
                            context.startActivity(intent)
                        }
                    },
                )
                else -> RunTab(
                    identityCount = identities.size,
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
private fun SettingsTab(
    settings: Settings,
    status: String,
    proxyStatus: String,
    publicIp: String,
    onChange: (Settings) -> Unit,
    identityCount: Int,
    pageIndex: Int,
    atEof: Boolean,
    importStats: ImportStats,
    onImport: () -> Unit,
    onContinue: () -> Unit,
    onPullFromApi: () -> Unit,
    onCheckIp: () -> Unit,
    onTestProxies: () -> Unit,
    onFetchFreeProxies: () -> Unit,
    onRequestBatteryExemption: () -> Unit,
) {
    Column(Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())) {
        if (status.isNotEmpty()) {
            Text(status, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.height(8.dp))
        }
        Text("身份来源", style = MaterialTheme.typography.titleSmall)
        Text(
            if (importStats.lines > 0) {
                "文件 ${importStats.lines} 行 · 有效 ${importStats.valid} 条 · 已载入 ${importStats.kept} 条"
            } else {
                "还没有导入身份（每行 姓名|身份证[|QQ]，大文件自动分批）"
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.primary,
        )
        Button(onClick = onImport) { Text("导入 sfz.txt") }
        Text(
            if (pageIndex > 0) {
                "第 $pageIndex 批 · 导入后自动解析并开跑，跑完自动读下一批"
            } else {
                "导入后自动解析 → 载入第一批 → 检测代理 → 直接开跑"
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.outline,
        )
        Spacer(Modifier.height(16.dp))

        Text("通道", style = MaterialTheme.typography.titleSmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("unified", "web", "mixed").forEach { channel ->
                FilterChip(
                    selected = settings.channel == channel,
                    onClick = { onChange(settings.copy(channel = channel)) },
                    label = { Text(if (channel == "mixed") "混合" else channel) },
                )
            }
        }

        Text(
            when (settings.channel) {
                "web" -> "web 通道：网页表单，需要图形验证码（已自动识别）"
                "mixed" -> "混合：每个账号随机走 unified 或 web"
                else -> "unified 通道：ptlogin 注册，字段最少"
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.outline,
        )

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
            supportingText = { Text("两个账号之间等多久，建议 15~30") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.width(180.dp),
        )

        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = settings.proxies,
            onValueChange = { onChange(settings.copy(proxies = it)) },
            label = { Text("代理池（一行一个，可留空走直连）") },
            placeholder = {
                Text(
                    "支持这些写法（一行一个）：\n" +
                        "127.0.0.1:8080\n" +
                        "http://user:pass@1.2.3.4:3128\n" +
                        "1.2.3.4:8080:user:pass\n" +
                        "user:pass:1.2.3.4:8080\n" +
                        "socks5://1.2.3.4:1080\n" +
                        "1.2.3.4,8080,user,pass"
                )
            },
            modifier = Modifier.fillMaxWidth().height(110.dp),
            textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
        )
        OutlinedTextField(
            value = settings.apiUrl,
            onValueChange = { onChange(settings.copy(apiUrl = it)) },
            label = { Text("代理商提取链接（可选）") },
            placeholder = { Text("https://share.proxy.qg.net/get?key=XXXX") },
            modifier = Modifier.fillMaxWidth(),
            textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
            singleLine = true,
        )
        OutlinedTextField(
            value = settings.apiAuth,
            onValueChange = { onChange(settings.copy(apiAuth = it)) },
            label = { Text("提取账号:密码（可选，会自动拼到每条代理）") },
            placeholder = { Text("Authkey:Authpwd") },
            modifier = Modifier.fillMaxWidth(),
            textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
            singleLine = true,
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = settings.apiNum.toString(),
                onValueChange = { onChange(settings.copy(apiNum = it.toIntOrNull() ?: 1)) },
                label = { Text("一次提取数量") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.width(150.dp),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = onCheckIp) { Text("查出口 IP") }
            if (publicIp.isNotEmpty()) {
                Spacer(Modifier.width(8.dp))
                Text(
                    publicIp,
                    style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onPullFromApi) { Text("从 API 提取") }
            OutlinedButton(onClick = onTestProxies) { Text("测试代理") }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onFetchFreeProxies) { Text("获取免费代理") }
            Text(
                if (settings.proxies.isBlank()) {
                    "（未配置，走直连）"
                } else {
                    "（已填 ${settings.proxies.lines().count { it.isNotBlank() }} 条）"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
                modifier = Modifier.align(Alignment.CenterVertically),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = settings.freeProxyCount.toString(),
                onValueChange = { onChange(settings.copy(freeProxyCount = it.toIntOrNull() ?: 25)) },
                label = { Text("免费代理保留数量") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.width(180.dp),
            )
        }
        if (proxyStatus.isNotEmpty()) {
            Text(
                proxyStatus,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("代理策略：", style = MaterialTheme.typography.bodySmall)
            listOf("round-robin" to "轮询", "random" to "随机").forEach { (value, label) ->
                FilterChip(
                    selected = settings.proxyStrategy == value,
                    onClick = { onChange(settings.copy(proxyStrategy = value)) },
                    label = { Text(label) },
                    modifier = Modifier.padding(start = 6.dp),
                )
            }
        }
        Spacer(Modifier.height(8.dp))
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
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = settings.keepAlive, onCheckedChange = { onChange(settings.copy(keepAlive = it)) })
            Spacer(Modifier.width(8.dp))
            Text("保活（前台服务 + 唤醒锁，锁屏/后台继续跑）")
        }
        OutlinedButton(onClick = onRequestBatteryExemption) {
            Text("忽略电池优化（可选，进一步防杀）")
        }

        Spacer(Modifier.height(12.dp))
        Text(
            "随机 UA：每个账号换一条；代理：每账号切一个（账号内所有请求同 IP）",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.outline,
        )
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
    identityCount: Int,
    running: Boolean,
    progress: Float,
    status: String,
    log: String,
    results: List<SubmitResult>,
    onStart: () -> Unit,
    onExport: (String) -> Unit,
) {
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text(
            if (identityCount > 0) "身份 $identityCount 条（设置里导入/续批）" else "还没有身份，去设置里导入",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.outline,
        )
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
