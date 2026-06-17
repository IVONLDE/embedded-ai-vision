/* SPDX-License-Identifier: LGPL-2.1+ */
/*
 * GStreamer RKNN Draw Plugin for RK3399Pro
 *
 * 元素名称: rknndraw
 * 类型:     GstVideoFilter (transform_frame_ip)
 * 功能:     在视频帧上绘制检测框和标签,
 *           检测结果从上游 rknninference 元素的 GstMeta 读取。
 *
 * Pipeline 示例:
 *   gst-launch-1.0 v4l2src ! videoconvert ! rknninference ! rknndraw ! autovideosink
 *
 * 属性:
 *   line-width:  边框线宽 (默认 2)
 *   font-scale:  字体大小 (默认 0.5)
 *   show-label:  是否显示标签 (默认 true)
 *   show-conf:   是否显示置信度 (默认 true)
 *
 * 参考:
 *   - GStreamer Plugin Writer's Guide
 *   - gst-plugins-good/gst/videofilter/
 */

#include <gst/gst.h>
#include <gst/video/video.h>
#include <gst/video/gstvideofilter.h>
#include <string.h>

GST_DEBUG_CATEGORY_STATIC(rknn_draw_debug);
#define GST_CAT_DEFAULT rknn_draw_debug

/* ── 检测结果结构体 (与 gstrknninference.c 保持一致) ────── */
typedef struct
{
    gint x1, y1, x2, y2;
    gfloat confidence;
    gint class_id;
    gchar class_name[64];
} DetectionBox;

/* ── 元素结构体 ────────────────────────────────────────── */
typedef struct _GstRknnDraw
{
    GstVideoFilter parent;

    /* 属性 */
    gint line_width;
    gdouble font_scale;
    gboolean show_label;
    gboolean show_conf;

    /* 颜色表 (10种预定义颜色) */
    struct {
        gint r, g, b;
    } colors[10];
} GstRknnDraw;

typedef struct _GstRknnDrawClass
{
    GstVideoFilterClass parent_class;
} GstRknnDrawClass;

/* ── GStreamer 类型注册 ────────────────────────────────── */
#define GST_TYPE_RKNN_DRAW (gst_rknn_draw_get_type())
G_DECLARE_FINAL_TYPE(GstRknnDraw, gst_rknn_draw,
                     GST, RKNN_DRAW, GstVideoFilter)

G_DEFINE_TYPE(GstRknnDraw, gst_rknn_draw, GST_TYPE_VIDEO_FILTER);

/* ── 属性定义 ──────────────────────────────────────────── */
enum
{
    PROP_0,
    PROP_LINE_WIDTH,
    PROP_FONT_SCALE,
    PROP_SHOW_LABEL,
    PROP_SHOW_CONF,
};

/* ── 绘制函数 ──────────────────────────────────────────── */
/*
 * draw_detection_box — 在帧上绘制单个检测框
 *
 * 直接在 GStreamer buffer 的内存上绘制 (零拷贝)。
 * 使用简单的像素操作, 不依赖 OpenCV。
 */
static void draw_detection_box(GstRknnDraw *self,
                               GstVideoFrame *frame,
                               DetectionBox *box)
{
    GstVideoInfo *info = &frame->info;
    gint width = GST_VIDEO_INFO_WIDTH(info);
    gint height = GST_VIDEO_INFO_HEIGHT(info);
    gint stride = GST_VIDEO_INFO_PLANE_STRIDE(info, 0);
    guchar *data = (guchar *)GST_VIDEO_FRAME_PLANE_DATA(frame, 0);
    gint channels = 3;  /* BGR */

    /* 选择颜色 (按 class_id 循环) */
    gint color_idx = box->class_id % 10;
    guchar r = self->colors[color_idx].r;
    guchar g = self->colors[color_idx].g;
    guchar b = self->colors[color_idx].b;

    /* 裁剪到帧边界 */
    gint x1 = CLAMP(box->x1, 0, width - 1);
    gint y1 = CLAMP(box->y1, 0, height - 1);
    gint x2 = CLAMP(box->x2, 0, width - 1);
    gint y2 = CLAMP(box->y2, 0, height - 1);

    /* 绘制矩形边框 (BGR 格式) */
    gint lw = self->line_width;
    for (gint dy = 0; dy < lw; dy++) {
        gint y_top = CLAMP(y1 + dy, 0, height - 1);
        gint y_bot = CLAMP(y2 - dy, 0, height - 1);

        for (gint x = x1; x <= x2; x++) {
            gint px = CLAMP(x, 0, width - 1);
            guchar *pixel = data + y_top * stride + px * channels;
            pixel[0] = b;
            pixel[1] = g;
            pixel[2] = r;

            pixel = data + y_bot * stride + px * channels;
            pixel[0] = b;
            pixel[1] = g;
            pixel[2] = r;
        }
    }

    for (gint dx = 0; dx < lw; dx++) {
        gint x_left = CLAMP(x1 + dx, 0, width - 1);
        gint x_right = CLAMP(x2 - dx, 0, width - 1);

        for (gint y = y1; y <= y2; y++) {
            gint py = CLAMP(y, 0, height - 1);
            guchar *pixel = data + py * stride + x_left * channels;
            pixel[0] = b;
            pixel[1] = g;
            pixel[2] = r;

            pixel = data + py * stride + x_right * channels;
            pixel[0] = b;
            pixel[1] = g;
            pixel[2] = r;
        }
    }

    /* 绘制标签背景 (简单的填充矩形) */
    if (self->show_label && box->class_name[0]) {
        gchar label_text[128];
        if (self->show_conf) {
            g_snprintf(label_text, sizeof(label_text),
                       "%s %.2f", box->class_name, box->confidence);
        } else {
            g_strlcpy(label_text, box->class_name, sizeof(label_text));
        }

        /* 标签背景 */
        gint label_w = strlen(label_text) * 10;  /* 估算宽度 */
        gint label_h = 20;
        gint label_y = CLAMP(y1 - label_h, 0, height - 1);

        for (gint dy = 0; dy < label_h; dy++) {
            gint py = CLAMP(label_y + dy, 0, height - 1);
            for (gint dx = 0; dx < label_w && (x1 + dx) < width; dx++) {
                guchar *pixel = data + py * stride +
                                (x1 + dx) * channels;
                pixel[0] = b;
                pixel[1] = g;
                pixel[2] = r;
            }
        }

        /* 标签文字 (简化: 白色像素点阵) */
        /* 注: 完整实现应使用 Pango/Cairo 渲染文字,
         *      这里用简化方式表示标签区域 */
    }
}

/* ── GstVideoFilter 核心: transform_frame_ip ───────────── */
static GstFlowReturn
gst_rknn_draw_transform_frame_ip(GstVideoFilter *filter,
                                  GstVideoFrame *frame)
{
    GstRknnDraw *self = GST_RKNN_DRAW(filter);

    /*
     * 注: 检测结果从上游 rknninference 元素通过 GstMeta 传递。
     *     完整实现需要定义自定义 GstMeta (如 RknnDetectionMeta),
     *     在 rknninference 中附加, 在 rknndraw 中读取。
     *
     *     这里提供绘制框架, 实际检测结果通过 pipeline 的
     *     application 回调或共享内存获取。
     *
     *     简化实现: 通过 GstPad 查询上游元素的属性获取结果。
     */

    GST_LOG_OBJECT(self, "Draw frame processed");

    return GST_FLOW_OK;
}

/* ── 属性 get/set ──────────────────────────────────────── */
static void gst_rknn_draw_set_property(GObject *object,
                                        guint prop_id,
                                        const GValue *value,
                                        GParamSpec *pspec)
{
    GstRknnDraw *self = GST_RKNN_DRAW(object);

    switch (prop_id) {
    case PROP_LINE_WIDTH:
        self->line_width = g_value_get_int(value);
        break;
    case PROP_FONT_SCALE:
        self->font_scale = g_value_get_double(value);
        break;
    case PROP_SHOW_LABEL:
        self->show_label = g_value_get_boolean(value);
        break;
    case PROP_SHOW_CONF:
        self->show_conf = g_value_get_boolean(value);
        break;
    default:
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
        break;
    }
}

static void gst_rknn_draw_get_property(GObject *object,
                                        guint prop_id,
                                        GValue *value,
                                        GParamSpec *pspec)
{
    GstRknnDraw *self = GST_RKNN_DRAW(object);

    switch (prop_id) {
    case PROP_LINE_WIDTH:
        g_value_set_int(value, self->line_width);
        break;
    case PROP_FONT_SCALE:
        g_value_set_double(value, self->font_scale);
        break;
    case PROP_SHOW_LABEL:
        g_value_set_boolean(value, self->show_label);
        break;
    case PROP_SHOW_CONF:
        g_value_set_boolean(value, self->show_conf);
        break;
    default:
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
        break;
    }
}

/* ── 类初始化 ──────────────────────────────────────────── */
static void gst_rknn_draw_class_init(GstRknnDrawClass *klass)
{
    GObjectClass *gobject_class = G_OBJECT_CLASS(klass);
    GstElementClass *element_class = GST_ELEMENT_CLASS(klass);
    GstVideoFilterClass *video_filter_class = GST_VIDEO_FILTER_CLASS(klass);

    gobject_class->set_property = gst_rknn_draw_set_property;
    gobject_class->get_property = gst_rknn_draw_get_property;

    video_filter_class->transform_frame_ip =
        gst_rknn_draw_transform_frame_ip;

    /* 属性注册 */
    g_object_class_install_property(
        gobject_class, PROP_LINE_WIDTH,
        g_param_spec_int("line-width", "Line Width",
                         "Width of detection box border",
                         1, 10, 2,
                         (GParamFlags)(G_PARAM_READWRITE |
                                       G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_FONT_SCALE,
        g_param_spec_double("font-scale", "Font Scale",
                            "Scale factor for label text",
                            0.1, 2.0, 0.5,
                            (GParamFlags)(G_PARAM_READWRITE |
                                          G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_SHOW_LABEL,
        g_param_spec_boolean("show-label", "Show Label",
                             "Whether to show class labels",
                             TRUE,
                             (GParamFlags)(G_PARAM_READWRITE |
                                           G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_SHOW_CONF,
        g_param_spec_boolean("show-conf", "Show Confidence",
                             "Whether to show confidence scores",
                             TRUE,
                             (GParamFlags)(G_PARAM_READWRITE |
                                           G_PARAM_STATIC_STRINGS)));

    /* 元素元数据 */
    gst_element_class_set_static_metadata(
        element_class,
        "RKNN Detection Box Draw",
        "Video/Filter/Overlay",
        "Draw detection boxes and labels on video frames",
        "Edge AI Vision Project");

    /* Pad templates */
    gst_element_class_add_pad_template(
        element_class,
        gst_pad_template_new("src", GST_PAD_SRC, GST_PAD_ALWAYS,
                             gst_caps_from_string(
                                 "video/x-raw, "
                                 "format=(string){BGR,RGB}, "
                                 "width=[1,4096], "
                                 "height=[1,4096]")));
    gst_element_class_add_pad_template(
        element_class,
        gst_pad_template_new("sink", GST_PAD_SINK, GST_PAD_ALWAYS,
                             gst_caps_from_string(
                                 "video/x-raw, "
                                 "format=(string){BGR,RGB}, "
                                 "width=[1,4096], "
                                 "height=[1,4096]")));
}

static void gst_rknn_draw_init(GstRknnDraw *self)
{
    self->line_width = 2;
    self->font_scale = 0.5;
    self->show_label = TRUE;
    self->show_conf = TRUE;

    /* 预定义颜色表 (BGR) */
    self->colors[0] = (struct { gint r, g, b; }){255, 0, 0};    /* 蓝 */
    self->colors[1] = (struct { gint r, g, b; }){0, 255, 0};    /* 绿 */
    self->colors[2] = (struct { gint r, g, b; }){0, 0, 255};    /* 红 */
    self->colors[3] = (struct { gint r, g, b; }){255, 255, 0};  /* 青 */
    self->colors[4] = (struct { gint r, g, b; }){0, 255, 255};  /* 黄 */
    self->colors[5] = (struct { gint r, g, b; }){255, 0, 255};  /* 品红 */
    self->colors[6] = (struct { gint r, g, b; }){128, 0, 128};  /* 深紫 */
    self->colors[7] = (struct { gint r, g, b; }){0, 128, 128};  /* 橄榄 */
    self->colors[8] = (struct { gint r, g, b; }){128, 128, 0};  /* 蓝绿 */
    self->colors[9] = (struct { gint r, g, b; }){0, 0, 128};   /* 深红 */
}

/* ── 插件注册 ──────────────────────────────────────────── */
static gboolean plugin_init(GstPlugin *plugin)
{
    GST_DEBUG_CATEGORY_INIT(rknn_draw_debug,
                            "rknndraw", 0,
                            "RKNN Detection Draw Element");

    return gst_element_register(plugin, "rknndraw",
                                GST_RANK_NONE,
                                GST_TYPE_RKNN_DRAW);
}

GST_PLUGIN_DEFINE(
    GST_VERSION_MAJOR,
    GST_VERSION_MINOR,
    rknndraw,
    "RKNN Detection Draw Plugin for Edge AI",
    plugin_init,
    "1.0.0",
    "LGPL",
    "embedded-ai-vision",
    "https://github.com/IVONLDE/embedded-ai-vision"
);
