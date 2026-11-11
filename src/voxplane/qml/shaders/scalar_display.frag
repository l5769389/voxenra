#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 dataRange; // source min, source span, window lower, window width
    vec2 imageSize;
    float inverted;
};
layout(binding = 1) uniform sampler2D source;
layout(binding = 2) uniform sampler2D colorLut;
vec2 sampleScalar(vec2 p) {
    vec4 texel = texture(source, (clamp(p,vec2(0.0),imageSize-1.0)+0.5)/imageSize);
    float normalized = dot(texel.rgb,vec3(65536.0,256.0,1.0))*(255.0/16777215.0);
    return vec2(dataRange.x+normalized*dataRange.y,texel.a);
}
void main() {
    vec2 pixel = clamp(qt_TexCoord0*imageSize-0.5,vec2(0.0),imageSize-1.0);
    vec2 p = floor(pixel), f = fract(pixel);
    vec2 a=sampleScalar(p), b=sampleScalar(p+vec2(1.0,0.0));
    vec2 c=sampleScalar(p+vec2(0.0,1.0)), d=sampleScalar(p+vec2(1.0,1.0));
    vec2 sampled = mix(mix(a,b,f.x),mix(c,d,f.x),f.y);
    float gray=clamp((sampled.x-dataRange.z)/dataRange.w,0.0,1.0);
    if (inverted > 0.5) gray=1.0-gray;
    if (sampled.y < 0.99999) gray=0.0;
    float index = floor(gray*255.0+0.00001);
    fragColor = texture(colorLut,vec2((index+0.5)/256.0,0.5))*qt_Opacity;
}
