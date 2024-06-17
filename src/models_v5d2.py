import torch 
import torch.nn as nn
import torch.nn.functional as F
import numpy as np

#from timm.models.layers.drop import DropPath


class LayerNorm(nn.Module):
    def __init__(self, dim, channel):
        super().__init__()
        self.norm = nn.LayerNorm([channel, dim])

    def forward(self, x):
        B, T, N, C = x.shape
        x = x.reshape(B * T, N, C)
        x = self.norm(x)
        x = x.reshape(B, T, N, C)
        return x


class MLP(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.fc1 = nn.Linear(dim, dim)
        self.fc2 = nn.Linear(dim, dim)
        self.dropout = nn.Dropout(0.1)
        self.act = nn.GELU()

    def forward(self, x):
        x = self.fc1(x)
        x = self.act(x)
        x = self.dropout(x)
        x = self.fc2(x)
        x = self.dropout(x)
        return x


class MSA(nn.Module):
    def __init__(self, dim, num_head=4):
        super().__init__()
        self.q = nn.Linear(dim, dim)
        self.k = nn.Linear(dim, dim)
        self.v = nn.Linear(dim, dim)
        self.u = nn.Linear(dim, dim)
        self.softmax = nn.Softmax(-1)
        self.num_head = num_head
        self.dropout = nn.Dropout(0.1)
        
    def forward(self, x, m=None):
        B, T, N, C = x.shape
        x = x.reshape(B * T, N, C)
        q = self.q(x).reshape(B * T, N, self.num_head, -1).transpose(1, 2)
        k = self.k(x).reshape(B * T, N, self.num_head, -1).transpose(1, 2)
        v = self.v(x).reshape(B * T, N, self.num_head, -1).transpose(1, 2)
        attn = q @ k.transpose(-1, -2) / np.sqrt(C)
        if m is not None:
            m = m.reshape(B, 1, 1, 1, N)
            m = torch.tile(m, (1, T, 1, 1, 1))
            m = m.reshape(B * T, 1, 1, N)
            attn = attn.masked_fill(m == 0, -1e9)
        attn = self.softmax(attn)
        attn = self.dropout(attn)
        x = (attn @ v).transpose(1, 2).reshape(B, T, N, C)
        x = self.u(x)
        x = self.dropout(x)
        return x


class MCA(nn.Module):
    def __init__(self, dim, num_head=4):
        super().__init__()
        self.q = nn.Linear(dim, dim)
        self.k = nn.Linear(dim, dim)
        self.v = nn.Linear(dim, dim)
        self.u = nn.Linear(dim, dim)
        self.softmax = nn.Softmax(-1)
        self.num_head = num_head
        self.dropout = nn.Dropout(0.1)
    
    def forward(self, x1, x2, m2=None):
        B1, T1, N1, C1 = x1.shape
        B2, T2, N2, C2 = x2.shape
        x1 = x1.transpose(1, 2).reshape(B1 * N1, T1, C1)
        x2 = x2.transpose(1, 2).reshape(B2 * N2, T2, C2)
        q = self.q(x1).reshape(B1 * N1, T1, self.num_head, -1).transpose(1, 2)
        k = self.k(x2).reshape(B2 * N2, T2, self.num_head, -1).transpose(1, 2)
        v = self.v(x2).reshape(B2 * N2, T2, self.num_head, -1).transpose(1, 2)
        attn = q @ k.transpose(-1, -2) / np.sqrt(C1)
        if m2 is not None:
            m2 = m2.reshape(B2, 1, 1, 1, T2)
            m2 = torch.tile(m2, (1, N2, 1, 1, 1))
            m2 = m2.reshape(B2 * N2, 1, 1, T2)
            attn = attn.masked_fill(m2 == 0, -1e9)
        attn = self.softmax(attn)
        attn = self.dropout(attn)
        x = (attn @ v).transpose(1, 2)
        x = x.reshape(B1, N1, T1, C1).transpose(1, 2)
        x = self.u(x)
        x = self.dropout(x)
        return x


class ChannelFusion(nn.Module):
    def __init__(self, dim, channel):
        super().__init__()
        self.msa = MSA(dim)
        self.mlp = MLP(dim)
        self.norm1 = LayerNorm(dim, channel)
        self.norm2 = LayerNorm(dim, channel)
        # self.droppath = DropPath(0.1)
        # self.drop2 = DropPath(0.1)
        # self.scale1 = nn.Parameter(torch.ones((1, 1, dim)), requires_grad=True)
        # self.scale2 = nn.Parameter(torch.ones((1, 1, dim)), requires_grad=True)

        # self.scale1 = nn.Parameter(1e-6 * torch.ones(1, 1, dim), requires_grad=True)
        # self.scale2 = nn.Parameter(1e-6 * torch.ones(1, 1, dim), requires_grad=True)
        

    def forward(self, x):
        # Attention
        h = self.norm1(x)
        h = self.msa(h)
        x = x + h
        # x = x + self.scale1 * h
        
        # MLP
        h = self.norm2(x)
        h = self.mlp(h)
        x = x + h
        # x = x + self.scale2 * h

        return x


class TemporalFusion(nn.Module):
    def __init__(self, dim, channel):
        super().__init__()
        self.msa = MSA(dim)
        self.mlp = MLP(dim)
        self.norm1 = LayerNorm(dim, channel)
        self.norm2 = LayerNorm(dim, channel)
        
    def forward(self, x, m):
        # Attention
        h = self.norm1(x)
        h = h.transpose(1, 2)
        h = self.msa(h, m)
        h = h.transpose(1, 2)
        x = x + h

        # MLP
        h = self.norm2(x)
        h = self.mlp(h)
        x = x + h
        return x


class CrossFusion(nn.Module):
    def __init__(self, dim, channel):
        super().__init__()
        self.mca = MCA(dim)
        self.mlp = MLP(dim)
        self.norm1_1 = LayerNorm(dim, channel)
        self.norm1_2 = LayerNorm(dim, channel)
        self.norm2 = LayerNorm(dim, channel)
        
    def forward(self, x1, x2, m2):
        # Attention
        h1 = self.norm1_1(x1)
        h2 = self.norm1_2(x2)   
        h = self.mca(h1, h2, m2)
        x = x1 + h

        # MLP
        h = self.norm2(x)
        h = self.mlp(h)
        x = x + h
        return x


class Stem(nn.Module):
    """ Stem: Representing EEG channels within different time interval """
    def __init__(self, input_dim, dim):
        super().__init__()
        self.norm1 = LayerNorm(dim, 62)
        self.norm2 = LayerNorm(dim, 62)
        self.norm3 = LayerNorm(dim, 62)
        # in_channels, out_channels, kernel_size, stride=1
        self.conv1 = nn.Conv1d(input_dim, dim, 2, 2)
        self.conv2 = nn.Conv1d(dim, dim, 2, 2)
        self.conv3 = nn.Conv1d(dim, dim, 2, 2)
        self.pool1 = nn.AvgPool1d(2, 2)
        self.pool2 = nn.AvgPool1d(2, 2)
        self.pool3 = nn.AvgPool1d(2, 2)
        self.dropout = nn.Dropout(0.1)
        self.act = nn.GELU()
        self.input_dim = input_dim
        self.hidden_dim = dim

    def forward(self, x0, p0, m0):
        # 여기서 8은 batch 사이즈
        # x0: torch.Size([8, 265, 62, 5])
        # p0: torch.Size([8, 265, 62, 64])
        # m0: torch.Size([8, 265])
        B, T, N = x0.shape[:3]  # 8, 265, 62
        
        # [8, 265, 62, 5] => [8, 5, 265, 62]


        x1 = x0.permute(0, 2, 3, 1).reshape(B * N, self.input_dim, -1)
        #print(x1.shape)
        # x1: torch.Size([496, 5, 265])
        x1 = self.conv1(x1)
        #print(x1.shape)
        # x1: torch.Size([496, 64, 132])
        x1 = x1.reshape(B, N, self.hidden_dim, -1).permute(0, 3, 1, 2)
       # print(x1.shape)
        
        x2 = x1.permute(0, 2, 3, 1).reshape(B * N, self.hidden_dim, -1)
        # x2: torch.Size([496, 64, 132])
        x2 = self.conv2(x2)
        # x2: torch.Size([496, 64, 66])
        x2 = x2.reshape(B, N, self.hidden_dim, -1).permute(0, 3, 1, 2)

        x3 = x2.permute(0, 2, 3, 1).reshape(B * N, self.hidden_dim, -1)
        # x3: torch.Size([496, 64, 66])
        x3 = self.conv3(x3)
        # x3: torch.Size([496, 64, 33])
        x3 = x3.reshape(B, N, self.hidden_dim, -1).permute(0, 3, 1, 2)

        p0 = p0.permute(0, 2, 3, 1).reshape(B * N, -1, T)
        p1 = self.pool1(p0)
        p2 = self.pool2(p1)
        p3 = self.pool3(p2)
        
        p1 = p1.reshape(B, N, self.hidden_dim, -1).permute(0, 3, 1, 2)
        p2 = p2.reshape(B, N, self.hidden_dim, -1).permute(0, 3, 1, 2)
        p3 = p3.reshape(B, N, self.hidden_dim, -1).permute(0, 3, 1, 2)
        
        m0 = m0.reshape(B, 1, T)
        m1 = self.pool1(m0)
        m2 = self.pool2(m1)
        m3 = self.pool3(m2)
                
        m1 = m1.reshape(B, -1)
        m2 = m2.reshape(B, -1)
        m3 = m3.reshape(B, -1)

        return x1, x2, x3, p1, p2, p3, m1, m2, m3


class Head(nn.Module):
    """ Head: Averaging EEG channels """

    def __init__(self, dim):
        super().__init__()
        self.conv = nn.Linear(dim, dim)
        self.norm = LayerNorm(dim, 62)
        self.act = nn.GELU()
        self.dropout = nn.Dropout(0.1)

    def forward(self, x):
        x = self.act(self.norm(self.conv(x)))
        x = x.mean([-2])
        x = self.dropout(x)
        return x

class decoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.msa = MSA(64)
        self.cnnt_layer1 = nn.Conv2d(132,265,kernel_size=(1,1),stride=1,padding=0)
        self.cnn_layer = nn.Conv1d(64,5,kernel_size=1,stride=1,padding=0)
        self.act = nn.GELU()
        self.mask_token = nn.Parameter(torch.zeros(1, 1, 64*62))
    def forward(self,y,p,m,cls_token):
        #de = self.linear(y)#주석
        #B, T, N = de.shape
        #de = de.reshape(B,132,62,64)
        de = self.cnnt_layer1(y)
        #de = de.permute(0,2,3,1)
        de = de + p
        de = de.transpose(1, 2)
        de = self.msa(de,m)
        #de = de.transpose(1, 2)
        B, T, N, C = de.shape
        de = de.reshape(B * T, N, C)
        de = de.transpose(1, 2)
        de = self.cnn_layer(de)
        de = de.transpose(1, 2)
        de = de.reshape(B,62,265,5)
        de = torch.cat((cls_token,de),dim=1)
        de = de.transpose(1, 2)
        #de = de[:,:,1:,:]
        return de


class FastSlow(nn.Module):
    def __init__(
        self,
        classes=3,  # 변경
        frames=265, 
        channels=62,
        input_dim=5,
        dim=64,
        topk=None
    ):
        super().__init__()
        self.classes = classes
        self.softmax = nn.Softmax(-1)
        self.stem = Stem(input_dim, dim)
        self.head = Head(dim)
        self.decoder = decoder()
        self.topk = topk
        
        self.channel_fusion1 = ChannelFusion(dim, channels)
        self.channel_fusion2 = ChannelFusion(dim, channels)
        self.channel_fusion3 = ChannelFusion(dim, channels)

        self.temporal_fusion1 = TemporalFusion(dim, channels)

        self.cross_fusion21 = CrossFusion(dim, channels)
        self.cross_fusion32 = CrossFusion(dim, channels)

        self.classifier = nn.Linear(dim, classes)
        self.embedding = nn.Linear(classes,64)
        self.flat = nn.Flatten()
        self.xembedding = nn.Linear(396,64)

        self.initialize_weights()

    def initialize_weights(self):
        for m in self.modules():
            if isinstance(m, (nn.Conv1d, nn.Linear)):
                nn.init.trunc_normal_(m.weight, 0.0, 0.05)
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0.0)
            elif isinstance(m, nn.LayerNorm):
                nn.init.constant_(m.weight, 1.0)
                nn.init.constant_(m.bias, 0.0)
        

    def forward(self, x, p, m):
        # Stem 
        # (input, position_embedding, mask)
        x1, x2, x3, p1, p2, p3, m1, m2, m3 = self.stem(x, p, m)
        
        #print("x1:",x1.shape)
        #print('x2:',x2.shape)
        #print('x3:',x3.shape)
        #print(p1.shape,p2.shape,p3.shape)

        """
            x1.shape : 8, 132, 62, 64
            x2.shape : 8, 66, 62, 64
            x3.shape : 8, 33, 62, 64
        """

        # Channel Attention∂
        # x1 = self.channel_fusion1(x1)
        # x2 = self.channel_fusion2(x2)
        # x3 = self.channel_fusion3(x3)

        x1 = x1 + p1
        x2 = x2 + p2
        x3 = x3 + p3

        # Cross Temporal Attention
        x2 = self.cross_fusion32(x2, x3, m3)
        x1 = self.cross_fusion21(x1, x2, m2)
        x_ = self.temporal_fusion1(x1, m1)
        #print("self.head(x):", x.shape)
        # Head
        x = self.head(x_)
        #print("self.head(x):", x.shape)
        # Framelevel Emotion prediction
        x = self.classifier(x)
        #xem = self.xembedding(self.flat(x))
        #print("self.classifier(x):", x.shape)
        # # EEG Emotion prediction (MIL)
        y = []
        B, T = x.shape[:2]  # 8, 132, 3 => 8, 132
        #print(x.shape)
        m1 = m1.reshape(B, T, 1)
        x = x.masked_fill(m1 == 0, -1e9)
        
        topk = T//self.topk
        for c in range(self.classes):
            s = x[:, :, c]
            i = torch.topk(s, topk, dim=-1)[1]
            yc = [torch.mean(x[b, i[b, :], c], dim=0) for b in range(B)]
            yc = torch.stack(yc, dim=0)
            y.append(yc)
        y = torch.stack(y, dim=-1)
        
        #y= torch.mean(x,dim=1)
        y_soft = self.softmax(y)
        #y_ = torch.argmax(y_soft, axis = -1, keepdim=True)+1
        cls_token = y_soft.unsqueeze(dim=-1)
        cls_token = cls_token.unsqueeze(dim=-1).repeat(1,1,265,5)
        recon = self.decoder(x_,p,m,cls_token)
        #em = self.embedding(y)

        #em = xem+em

        #em = torch.concat([em,y_soft],axis=1)

        return y,recon 