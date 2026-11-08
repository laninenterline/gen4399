package io.gen4399.webui;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.KeyEvent;
import android.view.Menu;
import android.view.MenuItem;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * gen4399 WebUI 的 Android 外壳。
 *
 * 注册逻辑跑在 Termux 里的 Python 服务上（`python -m gen4399.webui`），
 * 这个 APK 只负责把那个页面装进 WebView；连不上时弹框让用户改服务器地址。
 */
public class MainActivity extends Activity {
    private static final String DEFAULT_URL = "http://127.0.0.1:8765/";
    private static final String PREFS = "gen4399";
    private static final int MENU_SETTINGS = 1;

    private WebView web;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);

        web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, int code, String description, String failingUrl) {
                if (failingUrl != null && failingUrl.startsWith("http")) {
                    showSettingsDialog("连不上服务：" + description);
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                if (url == null || url.startsWith("http://127.0.0.1") || url.startsWith("http://localhost")) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) {
                    // 设备没有浏览器时静默忽略
                }
                return true;
            }
        });

        setContentView(web);
        load();
    }

    private void load() {
        web.loadUrl(prefs.getString("url", DEFAULT_URL));
    }

    private void showSettingsDialog(String hint) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        box.setPadding(pad, pad, pad, 0);

        if (hint != null) {
            TextView tip = new TextView(this);
            tip.setText(hint + "\n\n先在 Termux 跑：python -m gen4399.webui");
            box.addView(tip);
        }

        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        input.setText(prefs.getString("url", DEFAULT_URL));
        input.setSelection(input.getText().length());
        box.addView(input);

        new AlertDialog.Builder(this)
            .setTitle("服务器地址")
            .setView(box)
            .setPositiveButton("保存并重连", new DialogInterface.OnClickListener() {
                @Override
                public void onClick(DialogInterface dialog, int which) {
                    saveUrl(input.getText().toString());
                }
            })
            .setNegativeButton("取消", null)
            .show();
    }

    private void saveUrl(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (value.length() == 0) {
            value = DEFAULT_URL;
        }
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            value = "http://" + value;
        }
        if (!value.endsWith("/")) {
            value = value + "/";
        }
        prefs.edit().putString("url", value).apply();
        load();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, MENU_SETTINGS, 0, "服务器地址");
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == MENU_SETTINGS) {
            showSettingsDialog(null);
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && web != null && web.canGoBack()) {
            web.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
