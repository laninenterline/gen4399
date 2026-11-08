package io.gen4399.webui

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.KeyEvent
import android.view.Menu
import android.view.MenuItem
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/**
 * gen4399 WebUI 的 Android 外壳（Kotlin 版）。
 *
 * 注册逻辑跑在 Termux 里的 Python 服务上（`python -m gen4399.webui`），
 * 这个 APK 只负责把那个页面装进 WebView；连不上时弹框让用户改服务器地址。
 */
class MainActivity : Activity() {

    private lateinit var web: WebView
    private val prefs by lazy { getSharedPreferences(PREFS, Context.MODE_PRIVATE) }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)

        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = true
            settings.builtInZoomControls = true
            settings.displayZoomControls = false
            settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            webViewClient = object : WebViewClient() {
                override fun onReceivedError(
                    view: WebView,
                    request: WebResourceRequest,
                    error: WebResourceError,
                ) {
                    if (request.isForMainFrame) {
                        showSettingsDialog("连不上服务：${error.description}")
                    }
                }

                override fun shouldOverrideUrlLoading(
                    view: WebView,
                    request: WebResourceRequest,
                ): Boolean {
                    val url = request.url.toString()
                    if (url.startsWith(LOCAL_PREFIX) || url.startsWith(LOCAL_PREFIX_ALT)) {
                        return false
                    }
                    return try {
                        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                        true
                    } catch (ignored: Exception) {
                        true
                    }
                }
            }
        }

        setContentView(web)
        load()
    }

    private fun load() {
        web.loadUrl(prefs.getString(KEY_URL, DEFAULT_URL) ?: DEFAULT_URL)
    }

    private fun showSettingsDialog(hint: String?) {
        val density = resources.displayMetrics.density
        val pad = (16 * density).toInt()

        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, 0)
        }
        if (hint != null) {
            box.addView(TextView(this).apply {
                text = "$hint\n\n先在 Termux 跑：python -m gen4399.webui"
            })
        }
        val input = EditText(this).apply {
            inputType = InputType.TYPE_TEXT_VARIATION_URI
            setText(prefs.getString(KEY_URL, DEFAULT_URL))
            setSelection(text.length)
        }
        box.addView(input)

        AlertDialog.Builder(this)
            .setTitle("服务器地址")
            .setView(box)
            .setPositiveButton("保存并重连") { _, _ -> saveUrl(input.text.toString()) }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun saveUrl(raw: String?) {
        var value = raw?.trim().orEmpty()
        if (value.isEmpty()) value = DEFAULT_URL
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            value = "http://$value"
        }
        if (!value.endsWith("/")) value = "$value/"
        prefs.edit().putString(KEY_URL, value).apply()
        load()
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, MENU_SETTINGS, 0, "服务器地址")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == MENU_SETTINGS) {
            showSettingsDialog(null)
            return true
        }
        return super.onOptionsItemSelected(item)
    }

    @Deprecated("Deprecated in Java")
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && web.canGoBack()) {
            web.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    companion object {
        private const val PREFS = "gen4399"
        private const val KEY_URL = "url"
        private const val DEFAULT_URL = "http://127.0.0.1:8765/"
        private const val LOCAL_PREFIX = "http://127.0.0.1"
        private const val LOCAL_PREFIX_ALT = "http://localhost"
        private const val MENU_SETTINGS = 1
    }
}
