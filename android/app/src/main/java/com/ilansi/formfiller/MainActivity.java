package com.ilansi.formfiller;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.res.AssetManager;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Hosts the form filler's web UI in a WebView. The UI and its JSON API are
 * served by the project's own Python server (web_gui.py), which runs inside
 * the app on a loopback port.
 */
public class MainActivity extends Activity {
    private static final String TAG = "FormFiller";
    private static final String HOST = "127.0.0.1";
    private static final String SEED_DIR = "seed";
    private static final String DOCX_MIME =
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    private static final int REQUEST_PICK_TEMPLATE = 1;

    private WebView webView;
    private ValueCallback<Uri[]> fileChooserCallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        TextView loading = new TextView(this);
        loading.setText(R.string.loading);
        loading.setGravity(Gravity.CENTER);
        loading.setTextSize(18);
        setContentView(loading);

        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        webView.setWebViewClient(new Client());
        webView.setWebChromeClient(new ChromeClient());
        webView.setDownloadListener((url, userAgent, disposition, mime, length) ->
                handleDownload(Uri.parse(url)));

        new Thread(() -> {
            try {
                int port = startServer();
                runOnUiThread(() -> {
                    setContentView(webView);
                    webView.loadUrl("http://" + HOST + ":" + port + "/");
                });
            } catch (Throwable e) {
                Log.e(TAG, "Failed to start", e);
                runOnUiThread(() -> loading.setText(
                        getString(R.string.start_failed) + "\n\n" + e));
            }
        }).start();
    }

    private int startServer() throws IOException {
        File dataDir = getFilesDir();
        copySeed(SEED_DIR, dataDir);
        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(getApplicationContext()));
        }
        return Python.getInstance().getModule("android_app")
                .callAttr("start", dataDir.getAbsolutePath()).toInt();
    }

    /**
     * Copies the bundled forms.json, templates, configs and web UI into the
     * app's storage. Files already there are kept, so forms and templates
     * added or edited in the app survive updates -- except the web UI itself,
     * which always follows the installed version.
     */
    private void copySeed(String assetPath, File target) throws IOException {
        AssetManager assets = getAssets();
        String[] children = assets.list(assetPath);
        if (children != null && children.length > 0) {
            if (!target.isDirectory() && !target.mkdirs()) {
                throw new IOException("Cannot create " + target);
            }
            for (String child : children) {
                copySeed(assetPath + "/" + child, new File(target, child));
            }
            return;
        }
        boolean alwaysRefresh = assetPath.startsWith(SEED_DIR + "/web/");
        if (target.exists() && !alwaysRefresh) {
            return;
        }
        try (InputStream in = assets.open(assetPath);
             OutputStream out = new FileOutputStream(target)) {
            byte[] buffer = new byte[16384];
            int n;
            while ((n = in.read(buffer)) > 0) {
                out.write(buffer, 0, n);
            }
        }
    }

    private boolean isLocal(Uri uri) {
        return HOST.equals(uri.getHost());
    }

    /** The server's "download" link for a generated document: hand the file to another app. */
    private boolean handleDownload(Uri uri) {
        if (!isLocal(uri) || !"/api/download".equals(uri.getPath())) {
            return false;
        }
        String name = uri.getQueryParameter("file");
        File outputDir = new File(getFilesDir(), "output");
        File file = new File(outputDir, name == null ? "" : name);
        if (name == null || !outputDir.equals(file.getParentFile()) || !file.isFile()) {
            Toast.makeText(this, R.string.file_missing, Toast.LENGTH_LONG).show();
            return true;
        }
        Uri content = FileProvider.getUriForFile(this, getPackageName() + ".files", file);
        new AlertDialog.Builder(this)
                .setTitle(file.getName())
                .setPositiveButton(R.string.open, (d, w) -> sendDocument(Intent.ACTION_VIEW, content))
                .setNeutralButton(R.string.share, (d, w) -> sendDocument(Intent.ACTION_SEND, content))
                .setNegativeButton(R.string.cancel, null)
                .show();
        return true;
    }

    private void sendDocument(String action, Uri content) {
        Intent intent = new Intent(action);
        if (Intent.ACTION_SEND.equals(action)) {
            intent.setType(DOCX_MIME);
            intent.putExtra(Intent.EXTRA_STREAM, content);
        } else {
            intent.setDataAndType(content, DOCX_MIME);
        }
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(Intent.createChooser(intent, null));
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, R.string.no_app_for_docx, Toast.LENGTH_LONG).show();
        }
    }

    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (isLocal(uri)) {
                return handleDownload(uri);
            }
            // Google Forms / Sheets links open in the browser or their own app.
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
            } catch (ActivityNotFoundException e) {
                Log.w(TAG, "No app for " + uri);
            }
            return true;
        }
    }

    private class ChromeClient extends WebChromeClient {
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                         FileChooserParams params) {
            if (fileChooserCallback != null) {
                fileChooserCallback.onReceiveValue(null);
            }
            fileChooserCallback = callback;
            Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("*/*");
            intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{DOCX_MIME});
            try {
                startActivityForResult(
                        Intent.createChooser(intent, getString(R.string.pick_template)),
                        REQUEST_PICK_TEMPLATE);
            } catch (ActivityNotFoundException e) {
                fileChooserCallback = null;
                return false;
            }
            return true;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_PICK_TEMPLATE || fileChooserCallback == null) {
            return;
        }
        fileChooserCallback.onReceiveValue(
                WebChromeClient.FileChooserParams.parseResult(resultCode, data));
        fileChooserCallback = null;
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
