def get_ancestors(pedigree,pig):

    ancestors={}

    def dfs(p,d):

        if p is None:
            return

        ancestors[p]=d

        father=pedigree.get(p,{}).get("father")
        mother=pedigree.get(p,{}).get("mother")

        dfs(father,d+1)
        dfs(mother,d+1)

    dfs(pig,0)

    return ancestors


def compute_inbreeding(pedigree,pig):

    if pig not in pedigree:
        return 0

    sire=pedigree[pig]["father"]
    dam=pedigree[pig]["mother"]

    if sire is None or dam is None:
        return 0

    sire_anc=get_ancestors(pedigree,sire)
    dam_anc=get_ancestors(pedigree,dam)

    common=set(sire_anc.keys()) & set(dam_anc.keys())

    F=0

    for a in common:

        n1=sire_anc[a]
        n2=dam_anc[a]

        F+=0.5**(n1+n2+1)

    return F