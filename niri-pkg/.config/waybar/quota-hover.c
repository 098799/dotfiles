// quota-hover — waybar CFFI module: the Claude quota strip, with hover.
//
// The strip itself is drawn by ~/bin/quota-deck (its daemon writes
// $XDG_RUNTIME_DIR/quota-deck/{full,compact}.png and signals waybar
// SIGRTMIN+16). This module only shows that PNG and tells the daemon where the
// pointer is, over a datagram socket ($XDG_RUNTIME_DIR/quota-deck/ctl):
//
//   enter <x> <mon_x> <mon_y>   the pointer rests on the strip: show the deck.
//                               x = the strip's centre in output coordinates,
//                               mon_x/mon_y = the output, by its position.
//   leave                       the pointer left the strip.
//   click <x> <mon_x> <mon_y>   left click: pin the deck open / close it.
//
// Why C: waybar has no hover action, and a GTK3 tooltip waits a fixed ~500 ms.
// A CFFI module gets the real enter/leave events. Middle and right clicks stay
// in the module config (waybar's own on-click-* handling).
//
// Build (install.sh does this):
//   cc -shared -fPIC -O2 -o quota-hover.so quota-hover.c $(pkg-config --cflags --libs gtk+-3.0)
//
// Config keys: "image" (file name in the runtime dir, e.g. "full.png"),
// "scale" (the PNG's pixels per logical px: 1 or 2).

#include <gtk/gtk.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include "waybar_cffi_module.h"

const size_t wbcffi_version = 2;

// The daemon's image signal (SIGNAL in quota-deck, "signal" in modules.jsonc).
#define IMAGE_SIGNAL 16
// The pointer must rest this long before the deck opens: crossing the bar on the
// way to a browser tab should not flash an 860 px panel. Well under GTK's tooltip
// delay.
#define HOVER_MS 60

typedef struct {
    GtkWidget *area;
    cairo_surface_t *surface;
    char image[512];
    char ctl[108];  // sizeof sockaddr_un.sun_path
    int scale;
    int fd;
    guint hover_timer;
} Strip;

static void send_msg(Strip *s, const char *verb) {
    char msg[128];
    int x = 0, mx = 0, my = 0;
    GtkWidget *top = gtk_widget_get_toplevel(s->area);
    GtkAllocation a;
    gtk_widget_get_allocation(s->area, &a);
    gtk_widget_translate_coordinates(s->area, top, a.width / 2, 0, &x, &my);
    GdkWindow *win = gtk_widget_get_window(s->area);
    if (win) {
        GdkMonitor *mon = gdk_display_get_monitor_at_window(gdk_window_get_display(win), win);
        if (mon) {
            GdkRectangle g;
            gdk_monitor_get_geometry(mon, &g);
            mx = g.x;
            my = g.y;
        }
    }
    if (strcmp(verb, "leave") == 0)
        snprintf(msg, sizeof msg, "leave");
    else
        snprintf(msg, sizeof msg, "%s %d %d %d", verb, x, mx, my);
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    snprintf(addr.sun_path, sizeof addr.sun_path, "%s", s->ctl);
    // No daemon: the message is lost, and so is the deck. The strip still shows.
    sendto(s->fd, msg, strlen(msg), MSG_DONTWAIT, (struct sockaddr *)&addr, sizeof addr);
}

static void load(Strip *s) {
    GdkPixbuf *pb = gdk_pixbuf_new_from_file(s->image, NULL);
    if (!pb)
        return;
    if (s->surface)
        cairo_surface_destroy(s->surface);
    s->surface = gdk_cairo_surface_create_from_pixbuf(pb, s->scale, NULL);
    gtk_widget_set_size_request(s->area, gdk_pixbuf_get_width(pb) / s->scale,
                                gdk_pixbuf_get_height(pb) / s->scale);
    g_object_unref(pb);
    gtk_widget_queue_draw(s->area);
}

static gboolean on_draw(GtkWidget *w, cairo_t *cr, gpointer data) {
    Strip *s = data;
    if (!s->surface)
        return FALSE;
    int h = gtk_widget_get_allocated_height(w);
    double sh = cairo_image_surface_get_height(s->surface) / (double)s->scale;
    cairo_set_source_surface(cr, s->surface, 0, (h - sh) / 2);
    cairo_paint(cr);
    return FALSE;
}

static gboolean hover_fire(gpointer data) {
    Strip *s = data;
    s->hover_timer = 0;
    send_msg(s, "enter");
    return G_SOURCE_REMOVE;
}

static gboolean on_enter(GtkWidget *w, GdkEventCrossing *e, gpointer data) {
    Strip *s = data;
    if (e->detail == GDK_NOTIFY_INFERIOR)
        return FALSE;
    if (!s->hover_timer)
        s->hover_timer = g_timeout_add(HOVER_MS, hover_fire, s);
    return FALSE;
}

static gboolean on_leave(GtkWidget *w, GdkEventCrossing *e, gpointer data) {
    Strip *s = data;
    if (e->detail == GDK_NOTIFY_INFERIOR)
        return FALSE;
    if (s->hover_timer) {
        g_source_remove(s->hover_timer);
        s->hover_timer = 0;
        return FALSE;  // the deck never opened
    }
    send_msg(s, "leave");
    return FALSE;
}

static gboolean on_press(GtkWidget *w, GdkEventButton *e, gpointer data) {
    Strip *s = data;
    if (e->button != 1 || e->type != GDK_BUTTON_PRESS)
        return FALSE;  // middle / right: waybar's on-click-* from the config
    if (s->hover_timer) {
        g_source_remove(s->hover_timer);
        s->hover_timer = 0;
    }
    send_msg(s, "click");
    return TRUE;
}

static char *unquote(const char *json) {
    // ABI 2 hands every value over as JSON: "\"full.png\"\n" or "2\n".
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
    char *image = g_strdup("full.png");
    s->scale = 1;
    for (size_t i = 0; i < n; i++) {
        char *v = unquote(entries[i].value);
        if (strcmp(entries[i].key, "image") == 0) {
            g_free(image);
            image = g_strdup(v);
        } else if (strcmp(entries[i].key, "scale") == 0) {
            s->scale = atoi(v) > 0 ? atoi(v) : 1;
        }
        g_free(v);
    }
    snprintf(s->image, sizeof s->image, "%s/quota-deck/%s", rt ? rt : "/tmp", image);
    snprintf(s->ctl, sizeof s->ctl, "%s/quota-deck/ctl", rt ? rt : "/tmp");
    g_free(image);
    s->fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);

    GtkContainer *root = info->get_root_widget(info->obj);
    // The root is waybar's event box: enter/leave/press arrive there.
    gtk_widget_add_events(GTK_WIDGET(root),
                          GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK | GDK_BUTTON_PRESS_MASK);
    s->area = gtk_drawing_area_new();
    gtk_widget_set_name(s->area, "quota-strip");
    gtk_container_add(root, s->area);
    g_signal_connect(s->area, "draw", G_CALLBACK(on_draw), s);
    g_signal_connect(root, "enter-notify-event", G_CALLBACK(on_enter), s);
    g_signal_connect(root, "leave-notify-event", G_CALLBACK(on_leave), s);
    g_signal_connect(root, "button-press-event", G_CALLBACK(on_press), s);
    load(s);
    gtk_widget_show_all(GTK_WIDGET(root));
    return s;
}

void wbcffi_deinit(void *instance) {
    Strip *s = instance;
    if (s->hover_timer)
        g_source_remove(s->hover_timer);
    if (s->surface)
        cairo_surface_destroy(s->surface);
    if (s->fd >= 0)
        close(s->fd);
    g_free(s);
}

void wbcffi_refresh(void *instance, int sig) {
    if (sig == SIGRTMIN + IMAGE_SIGNAL)
        load(instance);
}

void wbcffi_update(void *instance) {}
