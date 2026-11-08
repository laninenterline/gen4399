package io.gen4399.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager

/**
 * 保活：跑批量时挂一个前台服务，同时拿 CPU 唤醒锁 + Wi-Fi 锁。
 *
 * 这样锁屏、切后台、息屏都不会把注册流程掐断——Android 会优先回收没有前台服务的进程。
 */
class KeepAliveService : Service() {

    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopForeground(true)
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_UPDATE -> {
                val text = intent.getStringExtra(EXTRA_TEXT) ?: "运行中…"
                notify(text)
                return START_STICKY
            }
        }

        createChannel()
        acquireLocks()
        val text = intent?.getStringExtra(EXTRA_TEXT) ?: "运行中…"
        startForeground(NOTIFICATION_ID, build(text))
        instance = this
        return START_STICKY
    }

    override fun onDestroy() {
        releaseLocks()
        instance = null
        super.onDestroy()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "注册任务",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "批量注册保持运行"
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
    }

    private fun build(text: String): Notification {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        } else {
            PendingIntent.FLAG_UPDATE_CURRENT
        }
        val pending = PendingIntent.getActivity(this, 0, intent, flags)
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return builder
            .setContentTitle("gen4399 正在注册")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .setContentIntent(pending)
            .build()
    }

    private fun notify(text: String) {
        val manager = getSystemService(NotificationManager::class.java) ?: return
        manager.notify(NOTIFICATION_ID, build(text))
    }

    private fun acquireLocks() {
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "gen4399:run").apply {
            setReferenceCounted(false)
            acquire(12 * 60 * 60 * 1000L)   // 上限 12 小时，防止忘记释放
        }
        val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        wifiLock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "gen4399:wifi").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun releaseLocks() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        wifiLock?.let { if (it.isHeld) it.release() }
        wifiLock = null
    }

    companion object {
        private const val CHANNEL_ID = "gen4399_run"
        private const val NOTIFICATION_ID = 4399
        private const val ACTION_STOP = "io.gen4399.app.STOP"
        private const val ACTION_UPDATE = "io.gen4399.app.UPDATE"
        private const val EXTRA_TEXT = "text"

        var instance: KeepAliveService? = null
            private set

        fun start(context: Context, text: String) {
            val intent = Intent(context, KeepAliveService::class.java).putExtra(EXTRA_TEXT, text)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun update(context: Context, text: String) {
            if (instance == null) return
            runCatching {
                context.startService(
                    Intent(context, KeepAliveService::class.java)
                        .setAction(ACTION_UPDATE)
                        .putExtra(EXTRA_TEXT, text)
                )
            }
        }

        fun stop(context: Context) {
            runCatching {
                context.startService(
                    Intent(context, KeepAliveService::class.java).setAction(ACTION_STOP)
                )
            }
            instance = null
        }
    }
}
