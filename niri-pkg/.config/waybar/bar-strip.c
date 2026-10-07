// bar-strip — waybar CFFI module: one bardeck strip, with hover, click and scroll.
//
// bardeck (~/bin/bardeck) draws every strip of the bar to
// $XDG_RUNTIME_DIR/bardeck/<strip>-<variant>.argb (with "per-output": true,
// <strip>-<variant>@<x>_<y>.argb, one per output by its logical position) and
// signals waybar SIGRTMIN+16. This module shows that picture and tells bardeck what the
// pointer does, one datagram each, on $XDG_RUNTIME_DIR/bardeck/ctl:
//
//   enter  <strip> <cx> <mx> <my> <px> <variant>   the pointer rests on the strip ("hover-ms")
//   leave  <strip> ...                   it left
//   click  <strip> ...                   left button
//   right  <strip> ...                   right button, with "right-click": true
//   scroll-up / scroll-down <strip> ...
//
//   cx = the strip's centre and px = the pointer, both in output coordinates;
//   mx my = the output's logical position (which output the bar is on).
//
// Why C: waybar has no hover action and a GTK3 tooltip waits ~500 ms; a CFFI module
// gets the real crossing events. Middle and right clicks stay in the module config
// (waybar's on-click-* handling, which runs before this one).
//
// Build (install.sh does it; restart waybar after):
//   cc -shared -fPIC -O2 -o bar-strip.so bar-strip.c $(pkg-config --cflags --libs gtk+-3.0)
//
// Config: "strip" (name), "variant" ("full" / "compact"), "scale" (the picture's pixels
// per logical px), "per-output" (bool), "hover-ms" (0 = no hover; default 70),
// "right-click" (bool: the right button goes to bardeck too).

#include <gtk/gtk.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#include "waybar_cffi_module.h"

const size_t wbcffi_version = 2;

#define IMAGE_SIGNAL 16  // SIGNAL in bardeck/core.py

typedef struct {
    GtkWidget *area;
    GtkWidget *root;
    cairo_surface_t *surface;
    char strip[64];
    char variant[32];
    char dir[256];
    char ctl[108];  // sizeof sockaddr_un.sun_path
    char loaded[512];
    struct timespec loaded_mtime;
    int scale;
    int per_output;
    int right_click;  // send the right button too ("right"), not waybar's on-click-right
    int hover_ms;
    int fd;
    int px;  // the pointer, strip coordinates, at the last event
    guint hover_timer;
    gboolean entered;  // "enter" was sent and no "leave" yet
    double scroll;     // smooth scroll so far: a touchpad swipe is many small events
} Strip;

static void monitor_pos(Strip *s, int *mx, int *my) {
    *mx = *my = 0;
    GdkWindow *win = gtk_widget_get_window(s->area);
    if (!win)
        return;
    GdkMonitor *mon = gdk_display_get_monitor_at_window(gdk_window_get_display(win), win);
    if (!mon)
        return;
    GdkRectangle g;
    gdk_monitor_get_geometry(mon, &g);
    *mx = g.x;
    *my = g.y;
}

static void send_msg(Strip *s, const char *verb) {
    char msg[200];
    int cx = 0, px = 0, y = 0, mx, my;
    GtkWidget *top = gtk_widget_get_toplevel(s->area);
    GtkAllocation a;
    gtk_widget_get_allocation(s->area, &a);
    gtk_widget_translate_coordinates(s->area, top, a.width / 2, 0, &cx, &y);
    gtk_widget_translate_coordinates(s->area, top, s->px, 0, &px, &y);
    monitor_pos(s, &mx, &my);
    snprintf(msg, sizeof msg, "%s %s %d %d %d %d %s", verb, s->strip, cx, mx, my, px, s->variant);
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    memcpy(addr.sun_path, s->ctl, sizeof addr.sun_path);
    // No bardeck: the message is lost, and so is the panel. The strip still shows.
    sendto(s->fd, msg, strlen(msg), MSG_DONTWAIT, (struct sockaddr *)&addr, sizeof addr);
}

static void path_of(Strip *s, char *out, size_t n) {
    if (s->per_output) {
        int mx, my;
        monitor_pos(s, &mx, &my);
        snprintf(out, n, "%s/%s-%s@%d_%d.argb", s->dir, s->strip, s->variant, mx, my);
    } else {
        snprintf(out, n, "%s/%s-%s.argb", s->dir, s->strip, s->variant);
    }
}

// A strip file: "BDK1", then width, height, stride (little-endian u32), then cairo's
// own premultiplied ARGB32 rows (bardeck/core.py write_strip). Raw, not PNG: this
// runs on waybar's main thread, every second for the system strip.
static void load(Strip *s) {
    char path[512];
    path_of(s, path, sizeof path);
    struct stat st;
    if (stat(path, &st) != 0)
        return;
    if (strcmp(path, s->loaded) == 0 && st.st_mtim.tv_sec == s->loaded_mtime.tv_sec &&
        st.st_mtim.tv_nsec == s->loaded_mtime.tv_nsec && s->surface)
        return;  // unchanged: the signal was for another strip
    gchar *buf = NULL;
    gsize len = 0;
    if (!g_file_get_contents(path, &buf, &len, NULL))
        return;
    guint32 hdr[3];
    if (len < 16 || memcmp(buf, "BDK1", 4) != 0) {
        g_free(buf);
        return;
    }
    memcpy(hdr, buf + 4, sizeof hdr);
    int w = (int)GUINT32_FROM_LE(hdr[0]), h = (int)GUINT32_FROM_LE(hdr[1]);
    int stride = (int)GUINT32_FROM_LE(hdr[2]);
    if (w <= 0 || h <= 0 || w > 16384 || h > 1024 || stride < w * 4 || len < 16 + (gsize)stride * h) {
        g_free(buf);
        return;  // half written or not ours: keep the old picture
    }
    cairo_surface_t *surf = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, w, h);
    if (cairo_surface_status(surf) != CAIRO_STATUS_SUCCESS) {
        cairo_surface_destroy(surf);
        g_free(buf);
        return;
    }
    cairo_surface_flush(surf);
    unsigned char *dst = cairo_image_surface_get_data(surf);
    int dstride = cairo_image_surface_get_stride(surf);
    for (int y = 0; y < h; y++)
        memcpy(dst + (gsize)y * dstride, buf + 16 + (gsize)y * stride, (gsize)w * 4);
    cairo_surface_mark_dirty(surf);
    cairo_surface_set_device_scale(surf, s->scale, s->scale);
    g_free(buf);
    if (s->surface)
        cairo_surface_destroy(s->surface);
    s->surface = surf;
    int lw = w / s->scale, lh = h / s->scale;
    int cw, ch;
    gtk_widget_get_size_request(s->area, &cw, &ch);
    if (cw != lw || ch != lh)
        gtk_widget_set_size_request(s->area, lw, lh);
    snprintf(s->loaded, sizeof s->loaded, "%s", path);
    s->loaded_mtime = st.st_mtim;
    gtk_widget_queue_draw(s->area);
}

static gboolean on_draw(GtkWidget *w, cairo_t *cr, gpointer data) {
    Strip *s = data;
    if (!s->surface)
        return FALSE;
    int h = gtk_widget_get_allocated_height(w);
    double sh = cairo_image_surface_get_height(s->surface) / (double)s->scale;  // logical px
    cairo_set_source_surface(cr, s->surface, 0, (h - sh) / 2);
    cairo_paint(cr);
    return FALSE;
}

static void on_map(GtkWidget *w, gpointer data) {
    Strip *s = data;
    s->loaded[0] = 0;  // the output is known now: per-output strips find their file
    load(s);
}

static gboolean hover_fire(gpointer data) {
    Strip *s = data;
    s->hover_timer = 0;
    s->entered = TRUE;
    send_msg(s, "enter");
    return G_SOURCE_REMOVE;
}

static gboolean on_enter(GtkWidget *w, GdkEventCrossing *e, gpointer data) {
    Strip *s = data;
    if (e->detail == GDK_NOTIFY_INFERIOR || s->hover_ms <= 0)
        return FALSE;
    s->px = (int)e->x;
    if (!s->hover_timer && !s->entered)
        s->hover_timer = g_timeout_add(s->hover_ms, hover_fire, s);
    return FALSE;
}

static gboolean on_motion(GtkWidget *w, GdkEventMotion *e, gpointer data) {
    ((Strip *)data)->px = (int)e->x;
    return FALSE;
}

static gboolean on_leave(GtkWidget *w, GdkEventCrossing *e, gpointer data) {
    Strip *s = data;
    if (e->detail == GDK_NOTIFY_INFERIOR)
        return FALSE;
    if (s->hover_timer) {
        g_source_remove(s->hover_timer);
        s->hover_timer = 0;
    }
    s->scroll = 0;
    if (s->entered) {
        s->entered = FALSE;
        send_msg(s, "leave");
    }
    return FALSE;
}

static gboolean on_press(GtkWidget *w, GdkEventButton *e, gpointer data) {
    Strip *s = data;
    if (e->type != GDK_BUTTON_PRESS || !(e->button == 1 || (e->button == 3 && s->right_click)))
        return FALSE;  // middle / right: waybar's on-click-* from the config
    s->px = (int)e->x;
    if (s->hover_timer) {
        g_source_remove(s->hover_timer);
        s->hover_timer = 0;
    }
    send_msg(s, e->button == 3 ? "right" : "click");
    return TRUE;
}

static gboolean on_scroll(GtkWidget *w, GdkEventScroll *e, gpointer data) {
    Strip *s = data;
    if (e->direction == GDK_SCROLL_UP) {
        send_msg(s, "scroll-up");
    } else if (e->direction == GDK_SCROLL_DOWN) {
        send_msg(s, "scroll-down");
    } else if (e->direction == GDK_SCROLL_SMOOTH) {
        // One step per whole unit of scroll, not one per event: a swipe sends dozens.
        if (e->is_stop) {
            s->scroll = 0;
            return FALSE;
        }
        gdouble dx, dy;
        if (!gdk_event_get_scroll_deltas((GdkEvent *)e, &dx, &dy))
            return FALSE;
        s->scroll += dy;
        while (s->scroll <= -1.0) {
            s->scroll += 1.0;
            send_msg(s, "scroll-up");
        }
        while (s->scroll >= 1.0) {
            s->scroll -= 1.0;
            send_msg(s, "scroll-down");
        }
    }
    return FALSE;
}

static char *unquote(const char *json) {
    // ABI 2 hands every value over as JSON: "\"full\"\n", "2\n", "true\n".
    char *v = g_strstrip(g_strdup(json));
    size_t n = strlen(v);
    if (n >= 2 && v[0] == '"' && v[n - 1] == '"') {
        memmove(v, v + 1, n - 2);
        v[n - 2] = 0;
    }
    return v;
}

void *wbcffi_init(const wbcffi_init_info *info, const wbcffi_config_entry *entries, size_t n) {
    Strip *s = g_new0(Strip, 1);
    const char *rt = g_getenv("XDG_RUNTIME_DIR");
    snprintf(s->strip, sizeof s->strip, "strip");
    snprintf(s->variant, sizeof s->variant, "full");
    s->scale = 1;
    s->hover_ms = 70;
    for (size_t i = 0; i < n; i++) {
        char *v = unquote(entries[i].value);
        const char *k = entries[i].key;
        if (strcmp(k, "strip") == 0)
            snprintf(s->strip, sizeof s->strip, "%s", v);
        else if (strcmp(k, "variant") == 0)
            snprintf(s->variant, sizeof s->variant, "%s", v);
        else if (strcmp(k, "scale") == 0)
            s->scale = atoi(v) > 0 ? atoi(v) : 1;
        else if (strcmp(k, "per-output") == 0)
            s->per_output = strcmp(v, "true") == 0;
        else if (strcmp(k, "right-click") == 0)
            s->right_click = strcmp(v, "true") == 0;
        else if (strcmp(k, "hover-ms") == 0)
            s->hover_ms = atoi(v);
        g_free(v);
    }
    snprintf(s->dir, sizeof s->dir, "%s/bardeck", rt ? rt : "/tmp");
    snprintf(s->ctl, sizeof s->ctl, "%.90s/bardeck/ctl", rt ? rt : "/tmp");
    s->fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);

    GtkContainer *root = info->get_root_widget(info->obj);
    s->root = GTK_WIDGET(root);
    gtk_widget_add_events(s->root, GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK | GDK_BUTTON_PRESS_MASK |
                                       GDK_POINTER_MOTION_MASK | GDK_SCROLL_MASK | GDK_SMOOTH_SCROLL_MASK);
    s->area = gtk_drawing_area_new();
    gtk_container_add(root, s->area);
    g_signal_connect(s->area, "draw", G_CALLBACK(on_draw), s);
    g_signal_connect(s->area, "map", G_CALLBACK(on_map), s);
    g_signal_connect(s->root, "enter-notify-event", G_CALLBACK(on_enter), s);
    g_signal_connect(s->root, "leave-notify-event", G_CALLBACK(on_leave), s);
    g_signal_connect(s->root, "motion-notify-event", G_CALLBACK(on_motion), s);
    g_signal_connect(s->root, "button-press-event", G_CALLBACK(on_press), s);
    g_signal_connect(s->root, "scroll-event", G_CALLBACK(on_scroll), s);
    load(s);
    gtk_widget_show_all(s->root);
    return s;
}

void wbcffi_deinit(void *instance) {
    Strip *s = instance;
    // The widgets may outlive this call by a moment during a reload: no handler may
    // reach the freed Strip.
    g_signal_handlers_disconnect_by_data(s->root, s);
    g_signal_handlers_disconnect_by_data(s->area, s);
    if (s->hover_timer)
        g_source_remove(s->hover_timer);
    if (s->surface)
        cairo_surface_destroy(s->surface);
    if (s->fd >= 0)
        close(s->fd);
    g_free(s);
}

void wbcffi_update(void *instance) {}

void wbcffi_refresh(void *instance, int sig) {
    if (sig == SIGRTMIN + IMAGE_SIGNAL)
        load(instance);
}
