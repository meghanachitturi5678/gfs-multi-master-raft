`include "../AL_Unit/ALU/alu.v"
`include "../AL_Unit/ADD/add_64bit.v"
`include "../AL_Unit/ADD/add_1bit.v"
`include "../AL_Unit/SUB/sub_64bit.v"
`include "../AL_Unit/XOR/xor_64bit.v"
`include "../AL_Unit/AND/and_64bit.v"
`include "fetch.v"
`include "decode.v"
`include "execute.v"
`include "memory.v"
`include "PIPE_con.v"

module PIPE();//pipe module

    reg clk;

    // F pipeline register
    reg [63:0] F_predPC = 0;

    // D pipeline register
    reg [3:0] D_stat = 4'b1000;
    reg [3:0] D_icode = 1;
    reg [3:0] D_ifun = 0;
    reg [3:0] D_rA = 0;
    reg [3:0] D_rB = 0;
    reg signed [63:0] D_valC = 0;
    reg [63:0] D_valP = 0;

    // E pipeline register
    reg [3:0] E_stat = 4'b1000;
    reg [3:0] E_icode = 1;
    reg [3:0] E_ifun = 0;
    reg signed [63:0] E_valC = 0;
    reg signed [63:0] E_valA = 0;
    reg signed [63:0] E_valB = 0;
    reg [3:0] E_dstE = 0;
    reg [3:0] E_dstM = 0;
    reg [3:0] E_srcA = 0;
    reg [3:0] E_srcB = 0;
    wire ZF;
    wire OF;
    wire SF;

    // M pipeline register
    reg [3:0] M_stat = 4'b1000;
    reg [3:0] M_icode = 1;
    reg M_Cnd = 0;
    reg signed [63:0] M_valE = 0;
    reg signed [63:0] M_valA = 0;
    reg [3:0] M_dstE = 0;
    reg [3:0] M_dstM = 0;

    // W pipeline register
    reg [3:0] W_stat = 4'b1000;
    reg [3:0] W_icode = 1;
    reg signed [63:0] W_valE = 0;
    reg signed [63:0] W_valM = 0;  
    reg [3:0] W_dstE = 0;
    reg [3:0] W_dstM = 0;

    // Fetch 
    wire [3:0] f_stat;
    wire [3:0] f_icode, f_ifun;
    wire [3:0] f_rA, f_rB;
    wire signed [63:0] f_valC;
    wire [63:0] f_valP, f_predPC;

    // Decode 
    wire [3:0] d_stat;
    wire [3:0] d_icode, d_ifun;
    wire signed [63:0] d_valC, d_valA, d_valB;
    wire [3:0] d_dstE, d_dstM;
    wire [3:0] d_srcA, d_srcB;

    // Registers
    wire signed [63:0] reg_file0;
    wire signed [63:0] reg_file1;
    wire signed [63:0] reg_file2;
    wire signed [63:0] reg_file3;
    wire signed [63:0] reg_file4;
