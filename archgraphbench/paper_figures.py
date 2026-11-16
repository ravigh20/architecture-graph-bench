"""Final-paper Figures 1–6. Figures 1–5 are method illustrations;
Figure 6 is plotted from newly computed rational-weight results."""
from __future__ import annotations
import csv
from pathlib import Path
from .io import read_json,write_json


def generate(output:Path) -> list[str]:
    """Render paper illustrations separately from the calculated weight-sensitivity plot."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch,FancyArrowPatch,Rectangle
    dest=output/'figures';dest.mkdir(parents=True,exist_ok=True);made=[]
    def canvas(title,foot,height=5):
        fig,ax=plt.subplots(figsize=(12,height));ax.set(xlim=(0,16),ylim=(0,10));ax.axis('off')
        fig.suptitle(title,fontsize=14,y=.97);fig.text(.5,.025,foot,ha='center',fontsize=8)
        return fig,ax
    def box(ax,x,y,text,w=3,h=1.2,fs=10):
        ax.add_patch(FancyBboxPatch((x-w/2,y-h/2),w,h,boxstyle='round,pad=.04',fill=False,linewidth=1))
        ax.text(x,y,text,ha='center',va='center',fontsize=fs)
        return x,y,w,h
    def arrow(ax,a,b,dashed=False):
        x,y,w,h=a;xx,yy,ww,hh=b;dx,dy=xx-x,yy-y
        if abs(dx)/max(w,ww)>abs(dy)/max(h,hh):
            p=(x+(w/2 if dx>=0 else -w/2),y);q=(xx-(ww/2 if dx>=0 else -ww/2),yy)
        else:
            p=(x,y+(h/2 if dy>=0 else -h/2));q=(xx,yy-(hh/2 if dy>=0 else -hh/2))
        ax.add_patch(FancyArrowPatch(p,q,arrowstyle='-|>',mutation_scale=13,linewidth=1.1,linestyle='--' if dashed else '-'))
    def save(fig,stem):
        fig.subplots_adjust(left=.04,right=.97,bottom=.13,top=.86)
        for suffix in ('svg','png'):
            p=dest/f'{stem}.{suffix}';fig.savefig(p,dpi=180,metadata={'Date':None} if suffix=='svg' else {})
            made.append(p.relative_to(output).as_posix())
        plt.close(fig)
    # Fixed hash salt makes vector identifiers deterministic; not a plot style.
    plt.rcParams['svg.hashsalt']='archgraphbench-proofread-candidate'
    fig,ax=canvas('Figure 1 · Representation validity','Method illustration. Representation fidelity does not establish correct reasoning or production security.')
    a=box(ax,2.5,7.4,'Architecture\nevidence',3.8)
    b=box(ax,8,7.4,'Reconstructed\ngraph',3.8)
    c=box(ax,13.5,7.4,'ArchGraphBench\nrepresentation check',3.8)
    arrow(ax,a,b);arrow(ax,b,c)
    box(ax,5,3.4,'Runtime conformance\nSeparate validation',4.4,1.8)
    box(ax,11,3.4,'Design-time reasoning\nSeparate validation',4.4,1.8)
    save(fig,'figure_1_representation_validity')
    fig,ax=canvas('Figure 2 · Typed assertions and source evidence','Illustrative graph only. Example locators are not experimental fixtures.',height=6)
    for lo,hi,title in [(0,2.1,'EXTERNAL'),(2.1,4.3,'EDGE'),(4.3,10.1,'APPLICATION'),(10.1,16,'DATA / SECURITY')]:
        ax.add_patch(Rectangle((lo,2.3),hi-lo,6.1,fill=False,linestyle=':',linewidth=.7))
        ax.text((lo+hi)/2,9.1,title,ha='center',fontsize=9)
    positions={'Client':(1.1,6.3),'Public API':(3.2,6.3),'Gateway':(5.5,6.3),'Order':(8.5,7.5),
               'Payment':(8.5,5.3),'Broker':(5.5,3.3),'Orders DB':(12,7.5),'Cards DB':(14.7,5.3),'IdP':(12,3.3),'SIEM':(14.7,3.3)}
    nodes={name:box(ax,*xy,name,w=1.8,h=.8,fs=9) for name,xy in positions.items()}
    observed=[('Client','Public API'),('Public API','Gateway'),('Gateway','Order'),('Gateway','Payment'),('Gateway','Broker'),('Order','Orders DB'),('Payment','Cards DB')]
    for a,b in observed:arrow(ax,nodes[a],nodes[b])
    for a,b in [('Payment','IdP'),('Broker','IdP')]:arrow(ax,nodes[a],nodes[b],True)
    ax.text(8,1.25,'a = (subject, predicate, object, type, locator, status, confidence, validity)\n'
            'Solid: observed in this illustration. Dashed: inferred. SIEM relation: unadjudicated.',ha='center',fontsize=9)
    save(fig,'figure_2_assertion_graph')
    write_json(dest/'figure_2_definition.json',{'kind':'METHOD_ILLUSTRATION','nodes':list(positions),
                'observed_edges':observed,'inferred_edges':[['Payment','IdP'],['Broker','IdP']],
                'unadjudicated':['SIEM'],'fixture':False})
    fig,ax=canvas('Figure 3 · Two references for one reconstruction','Method illustration. Missing support is not a negative fact.',height=6)
    full=box(ax,2.5,8,'Full evidence bundle',4);ref=box(ax,8,8,'Fixed architectural reference',4.4)
    semantic=box(ax,13.5,8,'Semantic comparison Ds',4)
    degraded=box(ax,2.5,4.7,'Available / degraded evidence',4)
    prediction=box(ax,8,4.7,'System-under-test prediction',4.4)
    support=box(ax,8,1.7,'Support reference: T / F / U / C',4.4)
    evidence=box(ax,13.5,1.7,'De, accepted count,\ncoverage and UCR',4)
    for a,b in [(full,ref),(full,degraded),(ref,semantic),(degraded,prediction),(degraded,support),(prediction,semantic),(prediction,evidence),(support,evidence)]:arrow(ax,a,b)
    save(fig,'figure_3_dual_reference')
    fig,ax=canvas('Figure 4 · Separate evaluation layers','Method illustration. These are separate measurements, not a composite risk score.',height=6)
    for y,text in [(8.5,'L1: Structure\nTyped node/edge F1 and alignment coverage'),(6.3,'L2: Security semantics\nZones, boundaries, identity and mediation'),(4.1,'L3: Evidence discipline\nSupport states, valid provenance, UCR and coverage'),(1.9,'L4: Query consequences\nDs and De with declared queries and weights')]:box(ax,8,y,text,12,1.6)
    save(fig,'figure_4_evaluation_layers')
    d=read_json(output/'diagnostics/summary.json')
    fig,ax=canvas('Figure 5 · Diagnostic workflow','Manifest annotations remain model-assisted. Archived-tool reanalysis: Section VII-F.',height=5)
    a=box(ax,2.6,7.4,'Structural constructions\nChains: '+', '.join(str(r['edges']) for r in d['bridge'])+' edges\nOne bridge; four targets',4.8,2,9)
    b=box(ax,8,7.4,f"Evidence-state enumeration\n{d['support_configurations']} configurations; {d['policy_count']} policies\n{len(d['thresholds'])} acceptance thresholds",4.8,2,9)
    c=box(ax,13.4,7.4,f"Weight sensitivity\n{d['weight_settings']} weight settings\n{d['distinct_plot_coordinates']} distinct coordinates",4.8,2,9)
    end=box(ax,8,3.0,'Separate raw outputs and reproducibility checks\nStructured records, predictions, CSV/JSON and hashes',14.8,1.8,10)
    for node in [a,b,c]:arrow(ax,node,end)
    save(fig,'figure_5_diagnostic_workflow')
    with (output/'diagnostics/weight_points.csv').open(newline='',encoding='utf-8') as stream:points=list(csv.DictReader(stream))
    x=[float(r['D_A']) for r in points];y=[float(r['D_B']) for r in points];counts=[int(r['multiplicity']) for r in points]
    fig,ax=plt.subplots(figsize=(7.2,6.3))
    # Match the submitted figure's explicit encodings, not an overall ranking.
    for label,marker,color,predicate in [
        ('D(A) < D(B): A lower','o','#0072B2',lambda a,b:a<b),
        ('D(B) < D(A): B lower','s','#B45309',lambda a,b:b<a),
        ('D(A) = D(B): tie','D','#606060',lambda a,b:a==b)]:
        indices=[i for i,(a,b) in enumerate(zip(x,y)) if predicate(a,b)]
        ax.scatter([x[i] for i in indices],[y[i] for i in indices],s=[35*counts[i] for i in indices],
                   marker=marker,color=color,label=label)
    ax.legend(loc='upper right',fontsize=8)
    bound=max([*x,*y])+.05
    ax.plot([0,bound],[0,bound],linestyle='--',linewidth=.8)
    ax.set(xlim=(0,bound),ylim=(0,bound),xlabel='D(A): one missed query',ylabel='D(B): two missed queries')
    fig.suptitle('Figure 6 · Query-weight sensitivity', fontsize=14, y=.97)
    ax.set_aspect('equal');ax.grid(True,alpha=.25)
    ax.text(.5,1.02,'Sensitivity to query weights',transform=ax.transAxes,ha='center',fontsize=9)
    fig.text(.5,.02,'All weight settings are constructed; marker area is proportional to multiplicity.',ha='center',fontsize=8)
    save(fig,'figure_6_weight_sensitivity')
    write_json(dest/'figure_6_data.json',{'settings_file':'diagnostics/weight_settings.csv','points':points,
                                        'ranks':d['weight_ranks'],'kind':'COMPUTED_DIAGNOSTIC_PLOT'})
    write_json(dest/'figure_roles.json',[{'figure':i,'kind':'COMPUTED_DIAGNOSTIC_PLOT' if i==6 else 'METHOD_ILLUSTRATION',
                'new_experimental_observation':False} for i in range(1,7)])
    return made
